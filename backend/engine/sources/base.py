"""信源适配器：把公开页面变成可入库的资料草稿。

三条纪律（对应 ROADMAP 第二期与合规红线）：

1. **只抓公开页面**：列表页 + 详情页，单源每次最多 `max_items` 条，发明确的
   User-Agent，超时 15 秒，响应体超过 2MB 直接放弃。不绕验证码、不重试登录态页面。
2. **失败不污染数据**：抓取或解析失败时只更新 `feed_sources.last_status`，
   已入库的资料原样保留。
3. **适配器是配置不是代码**：每个源一条 `feed_sources` 记录，`config_json` 里放
   `item_regex` / `link_pattern` / `include_keywords` 等参数；加新源不改代码。

入库走 `documents.store.upsert_document`，公共岗位池（`user_id` 为 NULL）自动按
`source_key` 去重，重复抓取只会更新、不会新增。
"""
from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from typing import Any, Iterable

import httpx

from engine.documents import normalize as doc_normalize
from engine.documents import store, text as text_util

USER_AGENT = "ZhideOfferJobsBot/0.1 (public job pages only; contact site admin)"
TIMEOUT_SECONDS = 15.0
MAX_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_ITEMS = 10


@dataclass(frozen=True)
class RawItem:
    """列表页/Feed 里的一条候选，还没抓正文。"""

    url: str
    title: str
    summary: str = ""
    published_at: float | None = None


@dataclass(frozen=True)
class SourceSpec:
    """一个信源的完整配置。"""

    id: str
    name: str
    kind: str
    url: str
    tier: int = 3
    license_note: str = ""
    config: dict[str, Any] = field(default_factory=dict)

    @property
    def max_items(self) -> int:
        value = self.config.get("max_items", DEFAULT_MAX_ITEMS)
        try:
            return max(1, min(int(value), 50))
        except (TypeError, ValueError):
            return DEFAULT_MAX_ITEMS


def spec_from_row(row: Any) -> SourceSpec:
    try:
        config = json.loads(row["config_json"] or "{}")
    except (TypeError, ValueError):
        config = {}
    return SourceSpec(
        id=row["id"], name=row["name"], kind=row["kind"], url=row["url"],
        tier=row["tier"], license_note=row["license_note"] or "", config=config,
    )


def http_get(url: str, *, client: httpx.Client | None = None) -> str:
    """抓取公开页面；任何异常都向上抛，由调用方记录 last_status。"""
    owned = client is None
    client = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True,
                                    headers={"User-Agent": USER_AGENT})
    try:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "html" not in content_type and "xml" not in content_type and "text" not in content_type:
                raise ValueError(f"不支持的内容类型：{content_type or '未知'}")
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > MAX_BYTES:
                    raise ValueError("页面超过 2MB，已放弃")
                chunks.append(chunk)
            raw = b"".join(chunks)
    finally:
        if owned:
            client.close()

    encoding = "utf-8"
    match = re.search(rb'charset=["\']?([\w-]+)', raw[:2048], re.I)
    if match:
        encoding = match.group(1).decode("ascii", "ignore")
    try:
        return raw.decode(encoding, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def fetch_items(spec: SourceSpec, *, client: httpx.Client | None = None) -> list[RawItem]:
    """按 kind 分派；未知 kind 直接报错，避免"静默抓不到"。"""
    if spec.kind == "rss":
        from engine.sources import rss
        return rss.items(http_get(spec.url, client=client), limit=spec.max_items)
    if spec.kind == "html_list":
        from engine.sources import html_list
        return html_list.items(http_get(spec.url, client=client), spec=spec)
    raise ValueError(f"未知信源类型：{spec.kind}")


def build_content(item: RawItem, spec: SourceSpec, *, client: httpx.Client | None = None) -> str:
    """详情页按需抓一次；抓不到就用列表页摘要，不让一条失败拖垮整轮。"""
    if not spec.config.get("fetch_detail"):
        return item.summary or item.title
    try:
        from engine.sources import html_list
        body = html_list.readable_text(http_get(item.url, client=client))
    except Exception:  # 详情页失败退回摘要，属于可接受的降级
        return item.summary or item.title
    return body if len(body) >= 40 else (item.summary or body or item.title)


def save_items(db: Any, spec: SourceSpec, items: Iterable[RawItem], *,
               client: httpx.Client | None = None) -> dict[str, int]:
    """把抓到的候选写入公共岗位池，返回新增/更新/跳过计数。"""
    created = updated = skipped = 0
    for item in items:
        url = text_util.normalize_text(item.url)
        title = text_util.normalize_text(item.title)
        if not url and not title:
            skipped += 1
            continue
        content = build_content(item, spec, client=client)
        if len(content) < int(spec.config.get("min_content_chars", 80)):
            # 平台入口页、导航链接的正文很短，存进去只会污染收件箱
            skipped += 1
            continue
        salary = doc_normalize.parse_salary(_salary_line(content))
        draft = store.DocumentDraft(
            kind="job",
            source="feed",
            title=title,
            company="",
            role=title,
            salary_text=salary.text,
            salary_min=salary.min,
            salary_max=salary.max,
            url=url,
            published_at=item.published_at,
            content_md=content,
            license_note=f"{spec.name}（tier {spec.tier}）{spec.license_note}".strip(),
            user_id=None,  # 公共岗位池
        )
        try:
            _, is_created = store.upsert_document(db, draft)
        except ValueError:
            skipped += 1
            continue
        if is_created:
            created += 1
        else:
            updated += 1
    return {"created": created, "updated": updated, "skipped": skipped}


def _salary_line(content: str) -> str:
    """从正文里找一行薪资。

    必须含数字才算命中：事业单位公告里常见"受聘人员工资待遇按国家规定执行"这类
    表述，没有数字的段落不是薪资信息，否则会把整段政策话术当成薪资入库。
    """
    for match in re.finditer(r"(?:薪\s*资|待遇|月薪|年薪|薪酬)[:：\s]*([^\n]{0,40})", content or ""):
        snippet = match.group(1).strip()
        if snippet and re.search(r"\d", snippet):
            return snippet
    return ""


def run_source(db: Any, spec: SourceSpec, *, client: httpx.Client | None = None) -> dict[str, Any]:
    """跑一个源：抓取 → 入库 → 记录状态。返回值直接给"试抓"按钮展示。"""
    started = time.time()
    try:
        items = fetch_items(spec, client=client)
        stats = save_items(db, spec, items, client=client)
        status = f"ok {stats['created']}+{stats['updated']}"
        db.execute(
            "UPDATE feed_sources SET last_run_at = ?, last_status = ? WHERE id = ?",
            (time.time(), status, spec.id),
        )
        return {"ok": True, "source": spec.id, "items": len(items), **stats,
                "seconds": round(time.time() - started, 2), "status": status}
    except Exception as exc:
        status = f"error: {type(exc).__name__}: {exc}"[:300]
        db.execute(
            "UPDATE feed_sources SET last_run_at = ?, last_status = ? WHERE id = ?",
            (time.time(), status, spec.id),
        )
        return {"ok": False, "source": spec.id, "error": status,
                "seconds": round(time.time() - started, 2)}


def upsert_spec(db: Any, spec: SourceSpec) -> None:
    db.execute(
        """INSERT INTO feed_sources(id, name, kind, url, tier, enabled, license_note, config_json)
           VALUES(?,?,?,?,?,1,?,?)
           ON CONFLICT(id) DO UPDATE SET
             name = excluded.name, kind = excluded.kind, url = excluded.url,
             tier = excluded.tier, license_note = excluded.license_note,
             config_json = excluded.config_json""",
        (spec.id, spec.name, spec.kind, spec.url, spec.tier, spec.license_note,
         json.dumps(spec.config, ensure_ascii=False)),
    )


def rss_datetime(value: str | None) -> float | None:
    """解析 RSS/Atom 时间；解析不出来就返回 None（不猜时间）。"""
    from email.utils import parsedate_to_datetime
    from datetime import datetime, timezone

    if not value:
        return None
    text = value.strip()
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError):
        pass
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except ValueError:
        return None


__all__ = [
    "RawItem", "SourceSpec", "spec_from_row", "http_get", "fetch_items",
    "build_content", "save_items", "run_source", "upsert_spec", "rss_datetime",
    "ElementTree",
]
