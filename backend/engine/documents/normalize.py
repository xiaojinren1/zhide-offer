"""岗位字段归一化：薪资、城市、年限、资料类别。

全部是纯函数：不读写数据库、不调模型。采集、粘贴导入、截图识别共用同一套
规则，保证同一份 JD 无论从哪条路进来，落到库里的字段口径一致。

口径约定（写清楚，避免以后各改各的）：

- `salary_min` / `salary_max` 一律折算为**元/月**整数
- 年薪按 12 个月折算；日薪按 21.75 个工作日折算；时薪按每天 8 小时折算
- 无法解析（"面议"、空值）返回 None，不猜
- `parse_salary()` 同时返回原始文本，前端展示用原文
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

WORKDAYS_PER_MONTH = 21.75
HOURS_PER_WORKDAY = 8
MONTHS_PER_YEAR = 12

DOC_KINDS = ("job", "jd", "note", "review", "tech", "example")
DOC_SOURCES = ("feed", "paste", "upload", "image", "manual")
VISIBILITIES = ("private", "pending", "public", "rejected")


@dataclass(frozen=True)
class Salary:
    """薪资解析结果。`min_` / `max_` 为元/月，无法解析时为 None。"""

    text: str
    min: int | None
    max: int | None
    months: int | None

    @property
    def parsed(self) -> bool:
        return self.min is not None or self.max is not None


def _to_int(value: float) -> int:
    return int(round(value))


def parse_salary(raw: object) -> Salary:
    """解析常见中文薪资写法；解析不出来就只保留原文。"""
    text = unicodedata.normalize("NFKC", str(raw or "")).strip()
    if not text:
        return Salary(text="", min=None, max=None, months=None)

    months_match = re.search(r"(\d{1,2})\s*薪", text)
    months = int(months_match.group(1)) if months_match else None

    lowered = text.lower()
    if "面议" in text or "待定" in text:
        return Salary(text=text, min=None, max=None, months=months)

    numbers = re.findall(r"\d+(?:\.\d+)?", lowered.replace(",", ""))
    if not numbers:
        return Salary(text=text, min=None, max=None, months=months)

    unit_scale = 1.0
    if re.search(r"\d\s*[kK千]", text):
        unit_scale = 1000.0
    elif "万" in text:
        unit_scale = 10000.0

    period = "month"
    if re.search(r"/\s*年|每年|年薪", text):
        period = "year"
    elif re.search(r"/\s*天|每天|日薪", text):
        period = "day"
    elif re.search(r"/\s*(小时|时)|时薪|每小时", text):
        period = "hour"

    divisor = {
        "month": 1.0,
        "year": float(MONTHS_PER_YEAR),
        "day": WORKDAYS_PER_MONTH,
        "hour": WORKDAYS_PER_MONTH * HOURS_PER_WORKDAY,
    }[period]

    values = [float(number) * unit_scale / divisor for number in numbers[:2]]
    if len(values) == 1:
        low = high = values[0]
    else:
        low, high = sorted(values)

    return Salary(text=text, min=_to_int(low), max=_to_int(high), months=months)


def normalize_city(raw: object) -> str:
    """取城市主体：去掉区县、后缀"市"与首尾分隔符。"""
    text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(raw or "")))
    if not text:
        return ""
    text = re.split(r"[·/\-—,，|]", text)[0]
    if text.endswith("市") and len(text) > 2:
        text = text[:-1]
    return text


def parse_experience(raw: object) -> tuple[int | None, int | None]:
    """解析年限要求，返回 (最低, 最高) 年；"不限"返回 (0, None)。"""
    text = unicodedata.normalize("NFKC", str(raw or "")).strip()
    if not text:
        return (None, None)
    if re.search(r"不限|无要求|经验不限", text):
        return (0, None)

    numbers = [int(number) for number in re.findall(r"\d+", text)]
    if not numbers:
        return (None, None)
    if len(numbers) == 1:
        return (numbers[0], None)
    low, high = sorted(numbers[:2])
    return (low, high)


def guess_kind(*, hint: object = "", source: str = "manual", text: object = "") -> str:
    """推断资料类别；拿不准就按 jd 处理（不丢数据，用户可以改）。"""
    value = str(hint or "").strip().lower()
    if value in DOC_KINDS:
        return value

    body = f"{value} {text}"
    if re.search(r"面试|一面|二面|三面|HR面|复盘", body):
        return "review"
    if re.search(r"笔记|总结|备忘|知识点", body):
        return "note"
    if source in {"feed", "paste"} and re.search(r"岗位|职责|任职要求|薪资", body):
        return "job"
    return "jd"


def clean_choice(value: object, allowed: tuple[str, ...], default: str) -> str:
    """枚举字段兜底：非法值退回默认值，不抛异常（脏数据不该中断采集）。"""
    text = str(value or "").strip().lower()
    return text if text in allowed else default
