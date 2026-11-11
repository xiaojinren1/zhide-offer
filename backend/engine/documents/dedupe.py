"""去重：URL 规范化、去重键、近似重复判定。

采集的生命线是"同一个岗位只能有一条记录"，所以去重键必须确定、可复算、
不依赖模型。这里的三个函数各有边界：

- `normalize_url()` 只做规范化，不发请求、不跟随跳转
- `source_key()` 生成入库唯一键，URL 优先，其次标题+公司，最后正文指纹
- `simhash64()` / `hamming()` 用于跨来源近似重复（不同站点同一条岗位）
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .text import normalize_text, tokenize

# 只影响归因、不影响内容的参数，一律剔除，否则同一岗位会因来源不同而重复入库
_TRACKING_PARAMS = frozenset({
    "from", "fromsource", "source", "spm", "scm", "share", "share_source",
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "referrer", "channel", "seid", "sessionid", "_t", "timestamp",
})

_TRACKING_PREFIXES = ("utm_",)

_DEFAULT_PORTS = {"http": "80", "https": "443"}


def normalize_url(raw: object) -> str:
    """小写协议与域名、去掉默认端口/锚点/追踪参数、参数排序、去掉尾斜杠。"""
    text = normalize_text(raw)
    if not text:
        return ""
    parts = urlsplit(text)
    if not parts.scheme and not parts.netloc:
        return text.rstrip("/")

    scheme = parts.scheme.lower() or "https"
    host = (parts.hostname or "").lower()
    port = parts.port
    netloc = host
    if port and str(port) != _DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{port}"

    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/")

    kept = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in _TRACKING_PARAMS or lowered.startswith(_TRACKING_PREFIXES):
            continue
        kept.append((key, value))
    query = urlencode(sorted(kept), doseq=True)

    return urlunsplit((scheme, netloc, path, query, ""))


def _digest(prefix: str, value: str) -> str:
    return prefix + hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def source_key(
    *,
    url: object = "",
    title: object = "",
    company: object = "",
    role: object = "",
    content: object = "",
) -> str:
    """生成入库唯一键：URL 优先，其次标题+公司+岗位，最后正文指纹。

    只要调用方按同一套口径补齐字段，同一岗位多次采集必然得到同一个键。
    """
    normalized_url = normalize_url(url)
    if normalized_url:
        return _digest("u:", normalized_url)

    identity = " ".join(
        part for part in (
            normalize_text(title).lower(),
            normalize_text(company).lower(),
            normalize_text(role).lower(),
        ) if part
    )
    if identity:
        return _digest("t:", re.sub(r"\s+", " ", identity))

    fingerprint = tokenize(content)
    if fingerprint is None or not fingerprint:
        return ""
    return _digest("x:", " ".join(sorted(set(fingerprint))))


def simhash64(text: object) -> int:
    """64 位 simhash；空文本返回 0（调用方应视为"无指纹"）。

    同样的 token 集合顺序无关，计数参与权重，所以换段顺序不会改变结果。
    """
    tokens = tokenize(text)
    if not tokens:
        return 0
    weights: dict[str, int] = {}
    for token in tokens:
        weights[token] = weights.get(token, 0) + 1

    vector = [0] * 64
    for token, weight in weights.items():
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bits = int.from_bytes(digest, "big")
        for index in range(64):
            vector[index] += weight if bits >> index & 1 else -weight
    result = 0
    for index in range(64):
        if vector[index] > 0:
            result |= 1 << index
    return result


def hamming(left: int, right: int) -> int:
    """两个 simhash 的汉明距离。"""
    return bin(left ^ right).count("1")


def near_duplicate(left: int, right: int, threshold: int = 3) -> bool:
    """指纹有效（非 0）且距离不超过阈值时视为同一条内容。"""
    if not left or not right:
        return False
    return hamming(left, right) <= threshold
