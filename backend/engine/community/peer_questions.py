"""从面经卡片里抽出"面试官问过的问题"，供出题时参考考察角度。

为什么用程序抽而不是让模型总结：
- 卡片是别人写的，里面可能有他们的公司、数字、项目；模型总结时很容易把这些**当成候选人的
  材料**带进题库，直接破坏"只用已确认事实"的铁律。
- 程序抽取只看句子形态（疑问句、带"问/考/追问"的句子），产出可复算、可解释，
  抽错了用户在预览里就能发现。

抽出来的只是**问题句式**，不含答案，也不含卡片里的事实判断。
"""
from __future__ import annotations

import re

MAX_QUESTIONS = 6
MAX_QUESTION_CHARS = 120

# 含这些词的句子大概率是"面试官问了什么"
_ASK_WORDS = ("问", "追问", "考", "答", "让", "要求", "手写", "说说", "讲讲", "解释")
# 明显是个人隐私或联系方式的行，整行跳过
_SKIP_MARKERS = ("已隐藏", "加我", "私聊", "微信", "手机号")

_SENTENCE_SPLIT = re.compile(r"[。！？!?\n；;]+")
_ENUM_PREFIX = re.compile(r"^\s*(?:[-*·•]|\d{1,2}[.、)）]|[（(]\d{1,2}[)）])\s*")


def _clean(line: str) -> str:
    text = _ENUM_PREFIX.sub("", line).strip()
    text = text.strip(" 　\"'“”‘’")
    return text


def looks_like_question(sentence: str) -> bool:
    """疑问句，或"问了/考了/让我"这类转述句，才算问题。"""
    text = sentence.strip()
    if len(text) < 4 or len(text) > MAX_QUESTION_CHARS:
        return False
    if any(marker in text for marker in _SKIP_MARKERS):
        return False
    if text.endswith(("？", "?")):
        return True
    if re.search(r"怎么|如何|为什么|是否|有没有|哪些|什么|多少|能不能", text):
        return True
    return any(word in text for word in _ASK_WORDS)


def extract_questions(body: str, *, limit: int = MAX_QUESTIONS) -> list[str]:
    """从卡片正文抽取问题句；保持原文顺序，去重，最多 limit 条。

    只返回问题句本身，不做改写——改写会引入不属于作者原意的措辞。
    """
    questions: list[str] = []
    seen: set[str] = set()
    for raw in _SENTENCE_SPLIT.split(str(body or "")):
        sentence = _clean(raw)
        if not sentence or not looks_like_question(sentence):
            continue
        key = re.sub(r"[\W_]+", "", sentence).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        questions.append(sentence if len(sentence) <= MAX_QUESTION_CHARS
                         else sentence[:MAX_QUESTION_CHARS] + "…")
        if len(questions) >= max(1, min(limit, MAX_QUESTIONS)):
            break
    return questions


def collect(cards: list[dict], *, per_card: int = 3, limit: int = 9) -> tuple[list[dict], list[dict]]:
    """把多张卡片压成"参考问题"与"引用信息"两份数据。

    返回 (references, questions)：
    - references：给前端展示"这次参考了哪几篇面经"（只含标题/公司/岗位/轮次）；
    - questions：给模型看的问题句（不含作者、公司、数字上下文，避免被当成事实）。
    """
    references: list[dict] = []
    questions: list[dict] = []
    seen: set[str] = set()
    for card in cards:
        extracted = extract_questions(card.get("body_md", ""), limit=per_card)
        if not extracted:
            continue
        card_id = str(card.get("id") or "")
        references.append({
            "id": card_id,
            "title": str(card.get("title") or "")[:80],
            "company": str(card.get("company") or "")[:40],
            "role": str(card.get("role") or "")[:40],
            "round": str(card.get("round") or "")[:20],
        })
        for question in extracted:
            key = re.sub(r"[\W_]+", "", question).casefold()
            if key in seen:
                continue
            seen.add(key)
            questions.append({"card_id": card_id, "question": question})
            if len(questions) >= limit:
                return references, questions
    return references, questions
