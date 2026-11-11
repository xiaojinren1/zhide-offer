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
import time
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from core import accounts, events
from core.llm import LLMError
from engine import documents
from engine.documents import normalize as doc_normalize
from engine.documents import paste as doc_paste
from engine.documents import screenshot as doc_screenshot
from engine.documents import store, text as text_util
from engine.jd_parser import parse_jd
from engine.resume_parser import MAX_IMAGE_BYTES, validate_image
from engine.sources import base as sources_base
from engine.sources import provinces as province_templates

router = APIRouter(prefix="/api/jobs", tags=["jobs"], dependencies=[Depends(accounts.require_csrf)])

MAX_TEXT = 20000
FETCH_ALL_SECONDS = 90.0
FETCH_ALL_INTERVAL = 0.8


class ImportRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_TEXT)
    title: str = ""
    company: str = ""
    city: str = ""
    salary: str = ""
    url: str = ""
    kind: str = "job"
    # paste 粘贴文本 / image 截图转写后保存；只作来源记录
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


_NEGOTIABLE = re.compile(r"面议|待定|详谈")


def _salary_fields(raw: str) -> tuple[str, int | None, int | None]:
    """把一段薪资文本转成 (展示文本, 下限, 上限)。

    解析不出数字就不写：早先把职责里的“Workflow”当成 K，存进去一条假薪资；
    脱敏的 `**-***元` 也一样，只是平台挡着，不能当成已知数字或乱码入库。
    """
    salary = doc_normalize.parse_salary(raw)
    if salary.parsed or _NEGOTIABLE.search(salary.text):
        return salary.text, salary.min, salary.max
    return "", None, None


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

    salary_text, salary_min, salary_max = _salary_fields(req.salary or _salary_hint(body))
    if not salary_text and re.search(r"\*{2,}", body):
        warnings.append("薪资是平台脱敏的（**-***元），没识别出具体数字，需要自己填")
    draft = store.DocumentDraft(
        kind=doc_normalize.guess_kind(hint=req.kind, source=req.source, text=body),
        source=doc_normalize.clean_choice(req.source, doc_normalize.DOC_SOURCES, "paste"),
        title=title or body.split("\n", 1)[0][:60],
        company=company,
        role=title,
        city=req.city,
        salary_text=salary_text,
        salary_min=salary_min,
        salary_max=salary_max,
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


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_TEXT)


@router.post("/analyze")
def analyze_paste(req: AnalyzeRequest, user: dict = Depends(accounts.require_user)):
    """粘贴识别：本地启发式猜岗位名/公司/城市/薪资，并告知是否已在收件箱。

    纯本地计算，不调模型、不抓网页，所以可以随输入频繁调用。
    """
    guess = doc_paste.analyze(req.text)
    draft = store.DocumentDraft(
        kind="job", source="paste", title=guess.title, company=guess.company,
        role=guess.title, url=guess.url, content_md=req.text, user_id=user["id"],
    )
    key = draft.resolved_key()
    duplicate = None
    if key:
        with accounts.connection() as db:
            row = db.execute(
                "SELECT id, title FROM documents WHERE COALESCE(user_id,'') = ? AND source_key = ?",
                (user["id"], key),
            ).fetchone()
        if row is not None:
            duplicate = {"id": row["id"], "title": row["title"]}
    return {"ok": True, "guess": guess.to_dict(), "duplicate": duplicate}


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


@router.post("/parse-image")
async def parse_job_screenshot(file: UploadFile = File(...)):
    """截图导入第一步：把岗位截图读成文字，回填到录入表单。

    **只识别不入库**：OCR 出来的字经常串行，存下去就是脏数据。前端拿这份文字和
    本地识别出的字段回填表单，用户核对、改完、自己点保存，才走 `/import`。
    """
    # 先按上限读，避免超大请求直接把图片吃进内存；校验细节交给 validate_image
    content = await file.read(MAX_IMAGE_BYTES + 1)
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="图片超过 10 MB，请压缩图片后重试")
    try:
        validate_image(content, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        body = doc_screenshot.read_job_screenshot(content, file.filename)
    except (LLMError, HTTPException):
        # 模型未配置（428）、额度/服务异常都要原样交给前端，不能盖成“识别失败”
        raise
    except ValueError as exc:  # 识别不出内容：明确失败，不返回半成品
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # 模型返回异常结构等
        events.emit_error("jobs_screenshot_parse", exc)
        return {"ok": False, "error": "截图识别失败，请重试或直接粘贴文字"}

    warnings: list[str] = []
    if len(body) > MAX_TEXT:
        body = body[:MAX_TEXT]
        warnings.append("截图文字过长，已截断，请确认正文是否完整")

    guess = doc_paste.analyze(body)
    return {
        "ok": True,
        "text": body,
        "guess": guess.to_dict(),
        "warnings": warnings,
    }


class SourceRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    id: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(pattern="^(rss|html_list)$")
    url: str = Field(min_length=1, max_length=500)
    tier: int = 3
    license_note: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


def _require_admin(user: dict) -> None:
    from api.user_stats import is_admin

    if not is_admin(user):
        raise HTTPException(status_code=403, detail="只有管理员可以管理信源")


@router.get("/sources")
def list_sources(user: dict = Depends(accounts.require_user)):
    """管理员查看信源列表与上次运行状态。"""
    _require_admin(user)
    with accounts.connection() as db:
        rows = db.execute(
            "SELECT id, name, kind, url, tier, enabled, license_note, last_run_at, last_status"
            " FROM feed_sources ORDER BY tier, name"
        ).fetchall()
    return {"ok": True, "items": [dict(row) for row in rows]}


@router.post("/sources")
def upsert_source(req: SourceRequest, user: dict = Depends(accounts.require_user)):
    """新增或修改一个信源配置；加新源不需要改代码。"""
    _require_admin(user)
    spec = sources_base.SourceSpec(
        id=req.id, name=req.name, kind=req.kind, url=req.url,
        tier=req.tier, license_note=req.license_note, config=req.config,
    )
    with accounts.connection() as db:
        sources_base.upsert_spec(db, spec)
    return {"ok": True, "source": req.id}


@router.post("/sources/{source_id}/fetch")
def fetch_source(source_id: str, user: dict = Depends(accounts.require_user)):
    """试抓一个信源：抓取并入库，返回计数与失败原因（不抛异常，便于后台展示）。"""
    _require_admin(user)
    with accounts.connection() as db:
        row = db.execute("SELECT * FROM feed_sources WHERE id = ?", (source_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="信源不存在")
        spec = sources_base.spec_from_row(row)
        result = sources_base.run_source(db, spec)
    return result


@router.get("/provinces")
def list_provinces(user: dict = Depends(accounts.require_user)):
    """省份信源选择器：模板 + 是否已启用 + 上次运行状态。"""
    _require_admin(user)
    with accounts.connection() as db:
        rows = db.execute(
            "SELECT id, url, enabled, last_run_at, last_status FROM feed_sources WHERE id LIKE 'prov-%'"
        ).fetchall()
    enabled = {row["id"]: dict(row) for row in rows}
    items = []
    for province in province_templates.list_provinces():
        current = enabled.get(province_templates.source_id(province["code"]))
        items.append({
            **province,
            "source_id": province_templates.source_id(province["code"]),
            "enabled": bool(current and current["enabled"]),
            "current_url": (current or {}).get("url") or "",
            "last_run_at": (current or {}).get("last_run_at"),
            "last_status": (current or {}).get("last_status") or "",
        })
    return {"ok": True, "items": items}


class ProvinceEnableRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    url: str = Field(default="", max_length=500)


@router.post("/provinces/{code}/enable")
def enable_province(code: str, req: ProvinceEnableRequest | None = None,
                    user: dict = Depends(accounts.require_user)):
    """启用某个省的招聘公告源；传 url 可覆盖模板地址。"""
    _require_admin(user)
    override = (req.url.strip() if req else "") or None
    try:
        with accounts.connection() as db:
            spec = province_templates.enable(db, code, url=override)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "source_id": spec.id, "url": spec.url, "name": spec.name}


@router.post("/sources/fetch-all")
def fetch_all_sources(user: dict = Depends(accounts.require_user)):
    """一键全抓：人工触发，串行跑完所有启用的信源。

    只做人工触发、不做定时：无人看着的批量抓取会带来封 IP、脏数据和合规责任转移，
    这些代价换不来多少体验。单轮 90 秒封顶，剩下的下一轮再跑。
    """
    _require_admin(user)
    deadline = time.time() + FETCH_ALL_SECONDS
    totals = {"created": 0, "updated": 0, "skipped": 0}
    results: list[dict[str, Any]] = []
    with accounts.connection() as db:
        rows = db.execute(
            "SELECT * FROM feed_sources WHERE enabled = 1 ORDER BY tier, name"
        ).fetchall()
        pending = list(rows)
        remaining = 0
        for index, row in enumerate(pending):
            if time.time() >= deadline and index < len(pending):
                remaining = len(pending) - index
                break
            spec = sources_base.spec_from_row(row)
            result = sources_base.run_source(db, spec)
            results.append({
                "source": result.get("source"),
                "ok": bool(result.get("ok")),
                "created": result.get("created", 0),
                "updated": result.get("updated", 0),
                "skipped": result.get("skipped", 0),
                "error": result.get("error", ""),
            })
            if result.get("ok"):
                for key in totals:
                    totals[key] += int(result.get(key, 0) or 0)
            if index < len(pending) - 1:
                time.sleep(FETCH_ALL_INTERVAL)

    failed = [item for item in results if not item["ok"]]
    return {"ok": True, "sources": len(results), "remaining": remaining,
            "failed": len(failed), **totals, "items": results}


@router.post("/provinces/{code}/disable")
def disable_province(code: str, user: dict = Depends(accounts.require_user)):
    _require_admin(user)
    with accounts.connection() as db:
        if not province_templates.disable(db, code):
            raise HTTPException(status_code=404, detail="该省尚未启用")
    return {"ok": True}


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
