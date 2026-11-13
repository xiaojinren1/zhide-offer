"""岗位与资料相关工具（Agent 的第二组手脚）。

与 `core/tools.py` 的简历质检工具**分开注册**：简历生成循环只该看到质检工具，
岗位检索只在岗位对话里出现。混在一组会让模型在写简历时跑去搜岗位。

沿用同一套原则：参数可判、返回值结构化、失败以 `{"error": ...}` 返回而不抛异常。
"""
from __future__ import annotations

import json
from typing import Any, Callable

from core import accounts
from engine import documents
from engine.documents import applications as doc_applications
from engine.documents import normalize as doc_normalize
from engine.documents import store, text as text_util

TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_jobs",
            "description": (
                "按关键词检索用户已收藏的岗位和资料（含公共岗位池），返回命中片段与 doc_id。"
                "用户问“有没有适合我的岗位”“我之前存的某个 JD”时调用；"
                "拿到 doc_id 后再用 get_job 看全文。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索词，如“数据开发”“测开 上海”"},
                    "limit": {"type": "integer", "description": "返回条数，默认 5，最大 20"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_job",
            "description": (
                "按 doc_id 取回岗位或资料的完整正文与解析结果。"
                "需要判断匹配度、做定制简历之前调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "string", "description": "search_jobs 返回的 doc_id"}},
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "import_document",
            "description": (
                "把用户给的岗位 JD 或资料正文存入收件箱。用户粘贴一段 JD、"
                "说“把这个岗位存下来”时调用。只接收正文，不抓取网页。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "岗位 JD 或资料正文"},
                    "title": {"type": "string", "description": "岗位名称；用户没给就留空"},
                    "company": {"type": "string", "description": "公司名称；用户没给就留空"},
                    "city": {"type": "string", "description": "城市；用户没给就留空"},
                    "salary": {"type": "string", "description": "薪资原文；用户没给就留空"},
                    "url": {"type": "string", "description": "来源链接；用户没给就留空"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_application",
            "description": (
                "更新某个岗位的投递状态（保存到看板）。用户说\"我投了这个\"\"约了面试\""
                "\"这个被拒了\"时调用。第一次只允许 saved；之后按状态机推进。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "岗位 doc_id"},
                    "stage": {
                        "type": "string",
                        "enum": list(doc_applications.STAGES),
                        "description": "目标状态",
                    },
                    "note": {"type": "string", "description": "备注，如\"走的内推\""},
                    "next_action": {"type": "string", "description": "下一次动作日期 YYYY-MM-DD，可空"},
                },
                "required": ["job_id", "stage"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": (
                "在用户的笔记、面经、JD 与写法范例里检索。用户问\"我之前记过什么\""
                "\"有没有同岗位的经验\"时调用；也可在改写简历前找同岗位写法参考。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索词"},
                    "kinds": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["job", "jd", "note", "review", "tech", "example"]},
                        "description": "限定资料类型，空表示全部",
                    },
                    "limit": {"type": "integer", "description": "返回条数，默认 5，最大 20"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_interview_experience",
            "description": (
                "查看用户从这个岗位发起过的模拟面试记录（标题、时间、总分）。"
                "用户问上上次这个岗位面得怎么样上时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "string", "description": "岗位 doc_id"}},
                "required": ["job_id"],
            },
        },
    },
]


def _job_brief(row: Any) -> dict[str, Any]:
    return {
        "job_id": row["id"],
        "title": row["title"],
        "company": row["company"],
        "city": row["city"],
        "salary_text": row["salary_text"],
        "kind": row["kind"],
        "updated_at": row["updated_at"],
    }


def build_executor(*, user_id: str) -> tuple[Callable[[str, dict], dict], list[str]]:
    """构造执行器。每次调用独立开连接，不跨请求持有事务。"""
    calls: list[str] = []

    def _exec(name: str, args: dict) -> dict:
        calls.append(name)
        payload = args or {}
        try:
            if name == "search_jobs":
                return _search_jobs(payload)
            if name == "get_job":
                return _get_job(payload)
            if name == "import_document":
                return _import_document(payload)
            if name == "save_application":
                return _save_application(payload)
            if name == "search_knowledge":
                return _search_knowledge(payload)
            if name == "get_interview_experience":
                return _get_interview_experience(payload)
            return {"error": f"unknown tool: {name}"}
        except ValueError as exc:
            return {"error": str(exc)}
        except Exception as exc:  # 工具失败不该杀死整个对话
            return {"error": f"{name} 执行失败：{exc}"}

    def _search_jobs(payload: dict) -> dict:
        query = str(payload.get("query") or "").strip()
        if not query:
            raise ValueError("query 不能为空")
        limit = max(1, min(int(payload.get("limit") or 5), 20))
        with accounts.connection() as db:
            hits = store.search(db, query, user_id=user_id,
                                 scopes=("private", "public"), limit=limit)
            items: list[dict[str, Any]] = []
            seen: set[str] = set()
            for hit in hits:
                if hit["doc_id"] in seen:
                    continue
                seen.add(hit["doc_id"])
                row = store.get_document(db, hit["doc_id"], user_id=user_id)
                if row is not None:
                    items.append({**_job_brief(row), "excerpt": hit["excerpt"]})
        return {"items": items, "total": len(items)}

    def _get_job(payload: dict) -> dict:
        job_id = str(payload.get("job_id") or "").strip()
        if not job_id:
            raise ValueError("job_id 不能为空")
        with accounts.connection() as db:
            row = store.get_document(db, job_id, user_id=user_id)
        if row is None:
            return {"error": "岗位不存在或无权查看"}
        try:
            structured = json.loads(row["structured_json"] or "{}")
        except (TypeError, ValueError):
            structured = {}
        return {**_job_brief(row), "url": row["url"], "content_md": row["content_md"],
                "structured": structured}

    def _import_document(payload: dict) -> dict:
        body = text_util.normalize_text(payload.get("text") or "")
        if not body:
            raise ValueError("text 不能为空")
        title = text_util.normalize_text(payload.get("title") or "")
        salary = doc_normalize.parse_salary(payload.get("salary") or "")
        draft = store.DocumentDraft(
            kind="job",
            source="paste",
            title=title or body.split("\n", 1)[0][:60],
            company=text_util.normalize_text(payload.get("company") or ""),
            role=title,
            city=payload.get("city") or "",
            salary_text=salary.text,
            salary_min=salary.min,
            salary_max=salary.max,
            url=text_util.normalize_text(payload.get("url") or ""),
            content_md=body,
            user_id=user_id,
        )
        with accounts.connection() as db:
            doc_id, created = store.upsert_document(db, draft)
        return {"job_id": doc_id, "created": created}

    def _save_application(payload: dict) -> dict:
        job_id = str(payload.get("job_id") or "").strip()
        stage = str(payload.get("stage") or "").strip()
        if not job_id:
            raise ValueError("job_id 不能为空")
        if stage not in doc_applications.STAGES:
            raise ValueError("stage 不合法，可选：" + "、".join(doc_applications.STAGES))
        with accounts.connection() as db:
            record = doc_applications.advance(
                db, user_id, job_id, stage=stage,
                note=payload.get("note") or "", next_action=payload.get("next_action") or "",
            )
        return {
            "job_id": record["doc_id"],
            "stage": record["stage"],
            "stage_label": record["stage_label"],
            "next_stage": record["next_stage"],
            "next_action_date": record["next_action_date"],
        }

    def _search_knowledge(payload: dict) -> dict:
        query = str(payload.get("query") or "").strip()
        if not query:
            raise ValueError("query 不能为空")
        limit = max(1, min(int(payload.get("limit") or 5), 20))
        kinds = [str(kind) for kind in (payload.get("kinds") or []) if str(kind).strip()] or None
        with accounts.connection() as db:
            hits = store.search(db, query, user_id=user_id,
                                scopes=("private", "public"), kinds=kinds, limit=limit)
            items: list[dict[str, Any]] = []
            for hit in hits:
                items.append({
                    "doc_id": hit["doc_id"],
                    "title": hit["title"],
                    "kind": hit["kind"],
                    "excerpt": hit["excerpt"][:400],
                })
        return {"items": items, "total": len(items)}

    def _get_interview_experience(payload: dict) -> dict:
        job_id = str(payload.get("job_id") or "").strip()
        if not job_id:
            raise ValueError("job_id 不能为空")
        with accounts.connection() as db:
            rows = db.execute(
                "SELECT id, title, saved_at, record_json FROM interview_records"
                " WHERE user_id = ? AND job_doc_id = ? ORDER BY saved_at DESC LIMIT 10",
                (user_id, job_id),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            score = None
            try:
                record = json.loads(row["record_json"] or "{}")
                report = (record.get("overall_feedback") or {}).get("report") or {}
                score = report.get("overall_score")
            except (TypeError, ValueError):
                score = None
            items.append({"id": row["id"], "title": row["title"],
                          "saved_at": row["saved_at"], "overall_score": score})
        return {"job_id": job_id, "items": items, "total": len(items)}

    known = [spec["function"]["name"] for spec in TOOL_SPECS]
    return _exec, known
