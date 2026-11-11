"""HTML 列表页适配器：按配置的正则取条目，按启发式抽正文。

不引入 BeautifulSoup：仓库现有依赖里没有它，而公开公告列表页结构简单，
标准库 `HTMLParser` 足够。两个函数分开，方便单独测试：

- `items(document, spec)` 从列表页取候选
- `readable_text(document)` 抽正文纯文本（去脚本/样式/导航）
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

from engine.documents import text as text_util
from engine.sources.base import RawItem, SourceSpec

DEFAULT_ITEM_REGEX = r'<a[^>]+href="([^"]+)"[^>]*>([^<]{6,120})</a>'
DEFAULT_INCLUDE = ("招聘", "公告", "公开", "招录", "选调", "岗位")
_SKIP_TAGS = {"script", "style", "nav", "header", "footer", "form", "noscript", "svg"}
_BLOCK_TAGS = {"p", "div", "section", "article", "li", "tr", "h1", "h2", "h3", "h4", "br", "td"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        # type: ignore[override]
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        # type: ignore[override]
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        # type: ignore[override]
        if not self._skip and data.strip():
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


def readable_text(document: str) -> str:
    """抽取可见正文；连续空行压成一段分隔，便于分块。"""
    parser = _TextExtractor()
    parser.feed(document)
    parser.close()
    lines = [re.sub(r"[ \t\u3000]+", " ", line).strip() for line in parser.text().split("\n")]
    kept = [line for line in lines if line]
    return text_util.normalize_text("\n\n".join(kept))


def _absolute(url: str, base: str) -> str:
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("//"):
        return f"https:{url}"
    from urllib.parse import urljoin
    return urljoin(base, url)


def items(document: str, *, spec: SourceSpec) -> list[RawItem]:
    """按 `config_json.item_regex` 取链接与标题，再按关键词与长度过滤。"""
    pattern = spec.config.get("item_regex") or DEFAULT_ITEM_REGEX
    include = spec.config.get("include_keywords") or list(DEFAULT_INCLUDE)
    exclude = spec.config.get("exclude_keywords") or []
    try:
        min_length = max(2, int(spec.config.get("min_title_length", 6)))
    except (TypeError, ValueError):
        min_length = 6
    try:
        compiled = re.compile(pattern, re.S)
    except re.error as exc:
        raise ValueError(f"item_regex 无效：{exc}") from exc

    results: list[RawItem] = []
    seen: set[str] = set()
    for match in compiled.finditer(document):
        if len(match.groups()) < 2:
            raise ValueError("item_regex 需要两个捕获组：链接与标题")
        url = _absolute(match.group(1), spec.url)
        title = text_util.normalize_text(_strip_tags(match.group(2)))
        if not title or len(title) < min_length or (url and url in seen):
            continue
        if include and not any(word in title for word in include):
            continue
        if exclude and any(word in title for word in exclude):
            continue
        seen.add(url)
        results.append(RawItem(url=url, title=title))
        if len(results) >= spec.max_items:
            break
    return results


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value or "")
