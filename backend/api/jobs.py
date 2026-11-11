"""岗位收件箱：导入、列表、详情、删除。

三条边界：

- **导入不依赖模型**：解析失败或模型未配置时按原文入库，把原因放进 `warnings`；
  "模型挂了就存不进去"是不可接受的失败方式。
- **只存结构化字段 + 正文 + 来源链接**，不存原始 HTML；链接抓取不在这里做
  （见 docs/plan-jobs-knowledge-community.md 的合规约定）。
- **可见性由 `engine.documents.store` 统一裁决**，接口层不自己拼权限条件。
"""
from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core import accounts, events
from engine import documents
from engine.documents import normalize as doc_normalize
from engine.documents import store, text as text_util
from engine.jd_parser import parse_jd

router = APIRouter(prefix="/api/jobs", tags=["jobs"], dependencies=[Depends(accounts.require_csrf)])

MAX_TEXT = 20000


class ImportRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_TEXT)
    title: str = ""
    company: str = ""
    city: str = ""
    salary: str = ""
    url: str = ""
    kind: str = "job"
    source: str = "paste"
    # 关掉解析可以省一次模型调用；采集任务会关掉，用户手工录入默认开启
    parse: bool = True


def _document_dict(row: Any) -> dict[str, Any]:
    """数据库行 → 前端契约；JSON 列在这里反序列化，前端不碰字符串。"""
    try:
        structured = json.loads(row["structured_json"] or "{}")
    except (TypeError, ValueError):
        structured = {}
    return {
        "id": row["id"],
        "kind": row["kind"],
        "source": row["source"],
        "title": row["title"],
        "company": row["company"],
        "role": row["role"],
        "city": row["city"],
        "salary_text": row["salary_text"],
        "salary_min": row["salary_min"],
        "salary_max": row["salary_max"],
        "experience": row["experience"],
        "education": row["education"],
        "url": row["url"],
        "content_md": row["content_md"],
        "structured": structured,
        "visibility": row["visibility"],
        "published_at": row["published_at"],
        "updated_at": row["updated_at"],
    }


def _salary_hint(body: str) -> str:
    """从正文里找一行薪资，找不到就交给用户手填。"""
    match = re.search(r"(?:薪\s*资|待遇|月薪|年薪)[:：\s]*([^\n]{0,40})", body)
    return match.group(1).strip() if match else ""


@router.post("/import")
def import_document(req: ImportRequest, user: dict = Depends(accounts.require_user)):
    body = text_util.normalize_text(req.text)
    if not body:
        raise HTTPException(status_code=422, detail="请粘贴岗位描述正文")

    warnings: list[str] = []
    structured: dict[str, Any] = {}
    title = text_util.normalize_text(req.title)
    company = text_util.normalize_text(req.company)

    if req.parse:
        try:
            parsed = parse_jd(body).to_dict()
            structured = parsed
            title = title or text_util.normalize_text(parsed.get("job_title") or "")
            company = company or text_util.normalize_text(parsed.get("company") or "")
        except Exception as exc:  # 模型不可用/超时/返回为空都按原文入库
            events.emit_error("jobs_import_parse", exc)
            warnings.append("模型未能解析这份 JD，已按原文入库；标题与公司可以手动补充")

    salary = doc_normalize.parse_salary(req.salary or _salary_hint(body))
    draft = store.DocumentDraft(
        kind=doc_normalize.guess_kind(hint=req.kind, source=req.source, text=body),
        source=doc_normalize.clean_choice(req.source, doc_normalize.DOC_SOURCES, "paste"),
        title=title or body.split("\n", 1)[0][:60],
        company=company,
        role=title,
        city=req.city,
        salary_text=salary.text,
        salary_min=salary.min,
        salary_max=salary.max,
        experience="",
        education="",
        url=text_util.normalize_text(req.url),
        content_md=body,
        structured=structured,
        user_id=user["id"],
    )

    with accounts.connection() as db:
        doc_id, created = store.upsert_document(db, draft)
        row = store.get_document(db, doc_id, user_id=user["id"])

    if row is None:  # 理论上不会发生；发生说明写入与读取的可见性规则不一致
        raise HTTPException(status_code=500, detail="资料已保存但读取失败，请刷新后重试")
    return {"ok": True, "id": doc_id, "created": created,
            "warnings": warnings, "document": _document_dict(row)}


@router.get("")
def list_jobs(
    kind: str | None = None,
    q: str | None = None,
    limit: int = 20,
    offset: int = 0,
    user: dict = Depends(accounts.require_user),
):
    kinds = [kind] if kind else None
    with accounts.connection() as db:
        if q and q.strip():
            hits = store.search(db, q, user_id=user["id"],
                                scopes=("private", "public"), kinds=kinds, limit=limit)
            seen: set[str] = set()
            items = []
            for hit in hits:
                if hit["doc_id"] in seen:
                    continue
                seen.add(hit["doc_id"])
                row = store.get_document(db, hit["doc_id"], user_id=user["id"])
                if row is not None:
                    items.append({**_document_dict(row), "matched_excerpt": hit["excerpt"]})
            return {"ok": True, "items": items, "total": len(items), "query": q}

        rows = store.list_documents(db, user_id=user["id"], kinds=kinds,
                                   limit=limit, offset=offset)
        return {"ok": True, "items": [_document_dict(row) for row in rows],
                "total": len(rows), "query": None}


@router.get("/{doc_id}")
def get_job(doc_id: str, user: dict = Depends(accounts.require_user)):
    with accounts.connection() as db:
        row = store.get_document(db, doc_id, user_id=user["id"])
        if row is None:
            raise HTTPException(status_code=404, detail="资料不存在或无权查看")
        chunks = db.execute(
            "SELECT chunk_index, text FROM knowledge_chunks WHERE doc_id = ? ORDER BY chunk_index",
            (doc_id,),
        ).fetchall()
    return {
        "ok": True,
        "document": _document_dict(row),
        "chunks": [{"index": chunk["chunk_index"], "text": chunk["text"]} for chunk in chunks],
    }


@router.delete("/{doc_id}")
def delete_job(doc_id: str, user: dict = Depends(accounts.require_user)):
    with accounts.connection() as db:
        if not store.delete_document(db, doc_id, user_id=user["id"]):
            raise HTTPException(status_code=404, detail="资料不存在或无权删除")
    return {"ok": True}
