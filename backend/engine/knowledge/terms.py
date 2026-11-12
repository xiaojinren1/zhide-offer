"""术语归一：同一件事的不同写法不能当成"没做过"。

问题：JD 写「数据仓库建模」，经历库写「数仓建模」，纯子串匹配会判成缺失——
这对候选人不公平，也会让匹配报告失真。

两种来源，都**可复算、可解释**：
1. 内置别名表（下面 `ALIASES`）：行业里公认的同义写法，人工维护、可审计；
2. 语料同现：同一批公开岗位里反复成对出现的写法（可选，见 `corpus_pairs`）。

为什么不直接把同义词喂给模型让它判断：那会变成模型的自由裁量，报告就不再可复核。
这里只做"文本里到底有没有这个说法"的判定，语义判断仍交给后续匹配阶段。

命中时返回值说明命中的是哪种写法（`matched_as`），报告里能写出"命中同义写法：数仓建模"，
用户看得见依据，也能自己判断这个同义是否成立。
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

# 同义组：一组内任意写法视为等价。全部用小写比对，中文不分词。
# 只收"行业里确实混用"的写法，不收近义但不等价的概念（如 数仓 与 数据湖）。
ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("数据仓库", "数仓", "data warehouse", "dw"),
    ("数据建模", "数仓建模", "数据仓库建模", "维度建模", "dimensional modeling"),
    ("数据治理", "数据质量治理", "数据资产管理"),
    ("指标口径", "指标定义", "指标口径统一", "口径治理"),
    ("实时计算", "流式计算", "流处理", "stream processing", "streaming"),
    ("离线计算", "批处理", "batch processing"),
    ("数据开发", "数仓开发", "etl开发", "etl 开发"),
    ("机器学习", "ml", "machine learning"),
    ("深度学习", "dl", "deep learning"),
    ("自然语言处理", "nlp", "nlp 算法"),
    ("大模型", "llm", "大语言模型", "large language model"),
    ("检索增强", "rag", "retrieval augmented generation"),
    ("提示词工程", "prompt engineering", "prompt 工程"),
    ("智能体", "agent", "ai agent", "多智能体", "multi-agent"),
    ("前后端分离", "前后端解耦"),
    ("持续集成", "ci", "持续集成部署", "ci/cd", "cicd"),
    ("自动化测试", "自动化用例", "automated testing"),
    ("性能优化", "性能调优", "性能改善"),
    ("高并发", "大并发", "high concurrency"),
    ("分布式系统", "分布式架构"),
    ("微服务", "microservice", "microservices"),
    ("容器化", "docker", "容器编排", "kubernetes", "k8s"),
    ("敏捷开发", "agile", "scrum"),
    ("用户增长", "增长", "growth"),
    ("转化率", "conversion", "cvr"),
    ("留存率", "留存", "retention"),
    ("日活", "dau", "daily active user"),
    ("月活", "mau", "monthly active user"),
    ("商业智能", "bi", "business intelligence"),
    ("人力资源", "hr", "人事"),
    ("供应链", "supply chain"),
    ("项目管理", "pm", "project management"),
    ("数据分析", "data analysis", "数据分析能力"),
    ("需求分析", "需求梳理", "需求调研"),
    ("跨团队协作", "跨部门协作", "跨团队沟通"),
)

# 拉丁写法要做词边界处理，否则 `bi` 会命中 `building`、`ml` 会命中 `html`
_LATIN = re.compile(r"[a-z0-9][a-z0-9+#./\- ]*")

_ALIAS_INDEX: dict[str, tuple[str, ...]] = {}
for group in ALIAS_GROUPS:
    normalized = tuple(item.strip().lower() for item in group if item.strip())
    for item in normalized:
        _ALIAS_INDEX[item] = normalized


def known_terms() -> tuple[str, ...]:
    """术语表里所有已知写法（去重、稳定顺序），供检索类场景当锚点用。"""
    return tuple(_ALIAS_INDEX)


def variants(term: object) -> tuple[str, ...]:
    """返回该术语的全部等价写法（含自身），去重且保序。"""
    key = str(term or "").strip().lower()
    if not key:
        return ()
    return _ALIAS_INDEX.get(key, (key,))


def _has_latin(text: str, needle: str) -> bool:
    """拉丁字母/数字写法按词边界判断，避免 `ml` 命中 `html`。"""
    pattern = r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _contains(text: str, needle: str) -> bool:
    if not needle:
        return False
    if _LATIN.fullmatch(needle) and needle.isascii():
        return _has_latin(text, needle)
    return needle in text


def find_match(term: object, text: object) -> str:
    """在文本里找该术语（含同义写法）；命中返回命中的那个写法，否则空串。

    优先返回术语本身，其次返回别名——报告里显示"命中同义写法"时不至于把原词当成别名。
    """
    key = str(term or "").strip().lower()
    body = str(text or "").lower()
    if not key or not body:
        return ""
    if _contains(body, key):
        return key
    for candidate in variants(key):
        if candidate != key and _contains(body, candidate):
            return candidate
    return ""


def present_terms(terms: Iterable[object], text: object) -> dict[str, str]:
    """批量判定：返回 {原术语: 命中的写法}，只含有命中的。"""
    body = str(text or "").lower()
    hits: dict[str, str] = {}
    for term in terms:
        matched = find_match(term, body)
        if matched:
            hits[str(term)] = matched
    return hits


def corpus_pairs(documents: Iterable[str], *, min_docs: int = 3) -> list[tuple[str, str]]:
    """从岗位语料里挑出"总是成对出现"的术语，供人工确认为别名。

    只做候选推荐，不自动生效：自动学习同义词一旦学错，报告会集体失真。
    返回按同现次数降序的 (术语A, 术语B) 列表，调用方决定是否写进 `ALIAS_GROUPS`。
    """
    co: Counter[tuple[str, str]] = Counter()
    docs = [str(doc or "").lower() for doc in documents if str(doc or "").strip()]
    known = sorted(_ALIAS_INDEX)
    for body in docs:
        present = [term for term in known if _contains(body, term)]
        for i, left in enumerate(present):
            for right in present[i + 1:]:
                if left == right or right in variants(left):
                    continue
                co[(left, right)] += 1
    return [pair for pair, count in co.most_common() if count >= min_docs]
