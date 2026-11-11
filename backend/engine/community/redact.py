"""投稿入库前的脱敏：把联系方式、证件号等人身信息替换成占位符。

为什么在服务端做：投稿一旦公开，手机号/邮箱/微信号就再也收不回来。前端提示只能
提醒，真正兜底必须在写库之前跑一遍。原则是**宁多遮不漏遮**——遮错了用户可以再补
一句"想要的可以私信我"，漏遮了就是真实的隐私泄漏。

不遮什么：公司名、岗位名、年份、薪资区间这些是内容价值所在，不是隐私。
"""
from __future__ import annotations

import re

PHONE = "[手机号已隐藏]"
EMAIL = "[邮箱已隐藏]"
ID_CARD = "[证件号已隐藏]"
QQ = "[QQ已隐藏]"
WECHAT = "[微信已隐藏]"

# 中国大陆手机号：1 开头 11 位，允许中间有空格/短横
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d[\s-]?\d{4}[\s-]?\d{4}(?!\d)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# 18 位身份证（含末位 X），再补一个 15 位老号码
_ID_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)|(?<!\d)\d{15}(?!\d)")
_QQ_RE = re.compile(r"(?:QQ|qq|扣扣|企鹅号)\s*[:：]?\s*(\d{5,12})")
_WECHAT_RE = re.compile(r"(?:微信|weixin|wechat|vx|VX|v信)\s*[号：:]?\s*([A-Za-z][-_A-Za-z0-9]{5,19}|\d{5,12})")


def redact(text: object) -> str:
    """替换文本中的隐私信息；多次调用结果稳定。"""
    value = str(text or "")
    if not value:
        return ""
    value = _PHONE_RE.sub(PHONE, value)
    value = _ID_RE.sub(ID_CARD, value)
    value = _EMAIL_RE.sub(EMAIL, value)
    value = _QQ_RE.sub(lambda m: m.group(0).replace(m.group(1), QQ), value)
    value = _WECHAT_RE.sub(lambda m: m.group(0).replace(m.group(1), WECHAT), value)
    return value


def redact_fields(*values: object) -> list[str]:
    """批量脱敏，保持位置对应，方便逐字段回填。"""
    return [redact(value) for value in values]
