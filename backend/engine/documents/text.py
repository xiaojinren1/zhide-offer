"""检索用的文本处理：清洗、分词、FTS5 查询表达式。

不引入 jieba 的理由：仓库当前依赖不包含分词库，而中文检索先用
"汉字二元组 + 拉丁词"就能达到可用召回，且完全可复算、无模型下载、
无 C 扩展。需要更好的分词时只替换 `tokenize()`，调用方不用改。

分词结果写进 `knowledge_chunks.text_tokens`（空格分隔），FTS5 用默认
unicode61 分词器即可命中；查询侧同样先分词再拼 MATCH 表达式。
"""
from __future__ import annotations

import re
import unicodedata

_CJK_RANGE = "\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff"
_TOKEN_RE = re.compile(f"[{_CJK_RANGE}]+|[0-9a-zA-Z][0-9a-zA-Z+#._-]*")

# FTS5 表达式里需要特殊处理的字符：双引号本身、以及会改变语法的运算符
_FTS_SPECIAL = re.compile(r'["^*():]')


def normalize_text(raw: object) -> str:
    """统一全角/半角、换行与空白，去掉首尾空白。"""
    text = unicodedata.normalize("NFKC", str(raw or ""))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def tokenize(text: object) -> list[str]:
    """英文按词、中文按二元组切分；单字中文单独成词。"""
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(normalize_text(text).lower()):
        chunk = match.group(0)
        if re.match(f"[{_CJK_RANGE}]", chunk):
            if len(chunk) == 1:
                tokens.append(chunk)
            else:
                tokens.extend(chunk[i:i + 2] for i in range(len(chunk) - 1))
        else:
            tokens.append(chunk)
    return tokens


def token_text(text: object) -> str:
    """写入 FTS 的形态：空格分隔的 token 串。"""
    return " ".join(tokenize(text))


def match_query(text: object) -> str | None:
    """把用户输入转成安全的 FTS5 MATCH 表达式；没有可用 token 时返回 None。"""
    tokens = [token for token in tokenize(text) if token.strip()]
    if not tokens:
        return None
    cleaned = (_FTS_SPECIAL.sub("", token).strip() for token in tokens)
    quoted = [f'"{token}"' for token in dict.fromkeys(cleaned) if token]
    return " OR ".join(quoted) if quoted else None
