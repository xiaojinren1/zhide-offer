"""RSS / Atom 适配器（标准库实现，不引第三方 feed 解析器）。"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from engine.sources.base import RawItem, rss_datetime
from engine.documents import text as text_util

_ATOM = "{http://www.w3.org/2005/Atom}"


def _strip_markup(value: str) -> str:
    """Feed 里的 description 常带 HTML，入库前只保留文字。"""
    if not value:
        return ""
    from engine.sources.html_list import readable_text
    return readable_text(value) if "<" in value else text_util.normalize_text(value)


def items(document: str, *, limit: int = 10) -> list[RawItem]:
    """解析 RSS 2.0 或 Atom；解析不了直接抛错（由调用方记录状态）。"""
    root = ET.fromstring(document.strip())
    results: list[RawItem] = []

    # RSS 2.0 / RSS 1.0
    for node in root.iter():
        if node.tag.split("}")[-1] != "item":
            continue
        link = _child_text(node, "link")
        title = _child_text(node, "title")
        summary = _child_text(node, "description") or _child_text(node, "summary")
        published = rss_datetime(_child_text(node, "pubDate") or _child_text(node, "date"))
        if link or title:
            results.append(RawItem(url=link, title=_strip_markup(title),
                                   summary=_strip_markup(summary), published_at=published))
        if len(results) >= limit:
            return results

    # Atom
    for node in root.iter(f"{_ATOM}entry"):
        link = ""
        for anchor in node.findall(f"{_ATOM}link"):
            if anchor.get("rel") in (None, "alternate"):
                link = anchor.get("href") or ""
                break
        title = node.findtext(f"{_ATOM}title") or ""
        summary = node.findtext(f"{_ATOM}summary") or node.findtext(f"{_ATOM}content") or ""
        published = rss_datetime(node.findtext(f"{_ATOM}updated") or node.findtext(f"{_ATOM}published"))
        if link or title:
            results.append(RawItem(url=link, title=_strip_markup(title),
                                   summary=_strip_markup(summary), published_at=published))
        if len(results) >= limit:
            return results

    return results


def _child_text(node: ET.Element, name: str) -> str:
    for child in node:
        if child.tag.split("}")[-1] == name:
            return (child.text or "").strip()
    return ""
