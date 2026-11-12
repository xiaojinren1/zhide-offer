"""写法范例检索：语料由 `data/knowledge/examples.json` 种子导入资料层，检索走 `documents`。

为什么要挪进资料层：JSON 文件只能靠改代码/改文件更新，既不能按岗位筛，也接不上已经建好的
FTS 索引。现在 `examples.json` 只做"首次导入的种子"，之后范例是普通资料（`kind='example'`，
`visibility='public'`），可以增删改查、可以走检索。

安全边界（和原来一致，不能松）：
- 范例只作为**写法风格参考**传给模型，prompt 里明确禁止照搬其中的事实与数字；
- 即便模型照抄，也会被可追溯校验（数字必须来自经历库）抓住；
- 检索只返回 `weak / strong / technique` 三件套，不把内部排序字段传进 prompt。
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

SEED_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "knowledge" / "examples.json"
EXAMPLE_KIND = "example"


def _clean(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _bigrams(text: str) -> set[str]:
    cleaned = _clean(text)
    return {cleaned[i:i + 2] for i in range(len(cleaned) - 1)} if len(cleaned) >= 2 else set()


def load_seed() -> dict[str, Any]:
    """读取种子文件；缺失或损坏时返回空库，不拖垮主流程。"""
    if not SEED_PATH.is_file():
        return {"methodology": [], "examples": []}
    try:
        data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"methodology": [], "examples": []}
    if not isinstance(data, dict):
        return {"methodology": [], "examples": []}
    data.setdefault("methodology", [])
    data.setdefault("examples", [])
    return data


def seed(db: sqlite3.Connection) -> int:
    """把种子导入资料层（幂等：同一 id 只导一次，已存在则跳过）。

    返回本次新写入的条数。不动用户资料，也不覆盖管理员后来改过的范例。
    """
    from engine.documents import normalize as doc_normalize

    examples = load_seed().get("examples") or []
    inserted = 0
    for item in examples:
        if not isinstance(item, dict):
            continue
        example_id = str(item.get("id") or "").strip()
        if not example_id:
            continue
        source_key = f"example:{example_id}"
        exists = db.execute(
            "SELECT 1 FROM documents WHERE source_key = ? AND COALESCE(user_id,'') = ''",
            (source_key,),
        ).fetchone()
        if exists:
            continue
        title = str(item.get("role_tags", [""])[0] if item.get("role_tags") else example_id)
        content = "\n".join(part for part in (
            f"弱写法：{item.get('weak', '')}",
            f"强写法：{item.get('strong', '')}",
            f"手法：{item.get('technique', '')}",
        ) if part.strip())
        db.execute(
            "INSERT INTO documents(id, user_id, kind, source, source_key, title, role, content_md,"
            " structured_json, visibility, fetched_at, created_at, updated_at)"
            " VALUES(?,NULL,?,?,?,?,?,?,?,'public',0,0,0)",
            (
                f"ex-{example_id}", EXAMPLE_KIND, "manual", source_key, title[:120],
                title[:120], content,
                json.dumps(item, ensure_ascii=False),
            ),
        )
        inserted += 1
    return inserted


def _score_example(example: dict[str, Any], jd_text: str, jd_keywords: list[str]) -> float:
    """相关度：标签命中（权重高）+ 关键词命中 + 二元组包含度。"""
    jd_low = (jd_text or "").lower()
    kw_low = [str(k).lower() for k in (jd_keywords or []) if k]
    score = 0.0
    for tag in (example.get("role_tags") or []) + (example.get("skill_tags") or []):
        value = str(tag).lower()
        if any(value == k or value in k or k in value for k in kw_low):
            score += 1.0
        elif value in jd_low:
            score += 0.6
    for keyword in example.get("keywords") or []:
        if keyword and str(keyword).lower() in jd_low:
            score += 0.5
    example_text = " ".join([
        str(example.get("strong") or ""), str(example.get("technique") or ""),
        " ".join(str(tag) for tag in (example.get("skill_tags") or [])),
    ])
    jd_bg, example_bg = _bigrams(jd_text), _bigrams(example_text)
    if jd_bg and example_bg:
        score += 0.3 * (len(jd_bg & example_bg) / max(1, len(example_bg)))
    return score


def _to_prompt_item(example: dict[str, Any]) -> dict[str, str]:
    """只给模型该看的字段，不带检索噪声。"""
    return {
        "id": str(example.get("id") or ""),
        "weak": str(example.get("weak") or ""),
        "strong": str(example.get("strong") or ""),
        "technique": str(example.get("technique") or ""),
    }


def retrieve(db: sqlite3.Connection | None, jd_text: str, jd_keywords: list[str],
             top_k: int = 3) -> list[dict[str, str]]:
    """检索最相关的 top_k 条范例。

    优先读资料层（`kind='example'`、公开）；库为空时退回种子文件，
    保证新环境第一次生成简历也能拿到范例，而不是"功能沉默失效"。
    """
    examples: list[dict[str, Any]] = []
    if db is not None:
        try:
            rows = db.execute(
                "SELECT structured_json FROM documents"
                " WHERE kind = ? AND visibility = 'public' AND COALESCE(user_id,'') = ''",
                (EXAMPLE_KIND,),
            ).fetchall()
            for row in rows:
                try:
                    item = json.loads(row["structured_json"] or "{}")
                except (TypeError, ValueError):
                    continue
                if isinstance(item, dict) and item.get("strong"):
                    examples.append(item)
        except sqlite3.Error:
            examples = []
    if not examples:
        examples = [item for item in (load_seed().get("examples") or []) if isinstance(item, dict)]

    if not examples:
        return []
    scored = [(_score_example(item, jd_text, jd_keywords), item) for item in examples]
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("id") or "")))
    return [_to_prompt_item(item) for score, item in scored[:max(0, top_k)] if score > 0]


def methodology() -> list[str]:
    return [str(item) for item in (load_seed().get("methodology") or []) if str(item).strip()]


def count(db: sqlite3.Connection | None = None) -> int:
    if db is not None:
        try:
            row = db.execute(
                "SELECT COUNT(*) FROM documents WHERE kind = ? AND visibility = 'public'",
                (EXAMPLE_KIND,),
            ).fetchone()
            if row and row[0]:
                return int(row[0])
        except sqlite3.Error:
            pass
    return len([item for item in (load_seed().get("examples") or []) if isinstance(item, dict)])
