"""范例库检索（轻量 RAG：精选语料 + 相关度检索，不用 embedding）。

为什么不用向量库：
- 精选语料只有几十条，二元组+关键词检索完全够用
- 上 embedding 要多一次模型调用、多一个故障点，比赛场合不值得
- 零新依赖，断网也能检索（语料在本地）

安全设计：范例只作为**写法风格参考**传给模型，prompt 里明确禁止照搬其中的
事实与数字；即便模型照抄，也会被可追溯校验（数字必须来自经历库）抓住。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

LIB_PATH = Path(__file__).resolve().parent.parent / "data" / "knowledge" / "examples.json"


def _clean(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _bigrams(text: str) -> set[str]:
    t = _clean(text)
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) >= 2 else set()


@lru_cache(maxsize=1)
def load_library() -> dict:
    """加载范例库（含方法论）。文件缺失或损坏时返回空库，不拖垮主流程。"""
    if not LIB_PATH.is_file():
        return {"methodology": [], "examples": []}
    try:
        data = json.loads(LIB_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"methodology": [], "examples": []}
    if not isinstance(data, dict):
        return {"methodology": [], "examples": []}
    data.setdefault("methodology", [])
    data.setdefault("examples", [])
    return data


def _score(example: dict, jd_text: str, jd_keywords: list[str]) -> float:
    """范例与 JD 的相关度：标签命中（权重高）+ 关键词命中 + 二元组包含度。"""
    jd_low = (jd_text or "").lower()
    kw_low = [k.lower() for k in (jd_keywords or []) if k]

    score = 0.0
    # 岗位/技能标签命中 JD 关键词
    for tag in (example.get("role_tags") or []) + (example.get("skill_tags") or []):
        t = tag.lower()
        if any(t == k or t in k or k in t for k in kw_low):
            score += 1.0
        elif t in jd_low:
            score += 0.6
    # 范例自带关键词出现在 JD 里
    for k in example.get("keywords") or []:
        if k and k.lower() in jd_low:
            score += 0.5
    # 文本相似度：JD 与范例正文的二元组包含度
    ex_text = " ".join([example.get("strong", ""), example.get("technique", ""),
                        " ".join(example.get("skill_tags") or [])])
    jd_bg, ex_bg = _bigrams(jd_text), _bigrams(ex_text)
    if jd_bg and ex_bg:
        score += 0.3 * (len(jd_bg & ex_bg) / max(1, len(ex_bg)))
    return score


def retrieve(jd_text: str, jd_keywords: list[str], top_k: int = 3) -> list[dict]:
    """检索最相关的 top_k 条范例（按分数降序，同分按 id 稳定排序）。

    只返回**该给模型看的字段**（id + 写法参考三件套），不带 role_tags/keywords
    等检索用噪声——调用方不需要知道内部结构，也不会误把噪声传进 prompt。
    """
    examples = load_library().get("examples") or []
    if not examples:
        return []
    scored = [(_score(e, jd_text, jd_keywords), e) for e in examples]
    scored.sort(key=lambda x: (-x[0], str(x[1].get("id") or "")))
    out = []
    for s, e in scored[:max(0, top_k)]:
        if s <= 0:
            continue
        out.append({
            "id": str(e.get("id") or ""),
            "weak": str(e.get("weak") or ""),
            "strong": str(e.get("strong") or ""),
            "technique": str(e.get("technique") or ""),
        })
    return out


def methodology() -> list[str]:
    return list(load_library().get("methodology") or [])


def count() -> int:
    return len(load_library().get("examples") or [])
