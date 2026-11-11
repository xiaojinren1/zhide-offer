"""粘贴文本的本地识别：把一段 JD 里的岗位名、公司、城市、薪资挑出来。

为什么不用模型：粘贴导入是高频动作，走模型要等接口、还可能超时失败。这里先用
可复算的启发式跑一遍（毫秒级、离线可用），识别不出来的字段留空交给用户或后续的
`parse_jd`；**不猜**——猜错的字段比留空更难发现。

识别口径：
- 岗位名：优先取含职位关键词的短行，否则取第一行
- 公司：`公司：` 前缀 → 招聘单位/单位名称 → 以公司/单位后缀结尾的短行
- 城市：显式"工作地点/城市" → 常见城市名表 → "北京·朝阳区" 这类写法
- 薪资/年限/学历：交给 `normalize.parse_salary` 与固定正则
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .normalize import parse_experience, parse_salary
from .text import normalize_text

_URL_RE = re.compile(
    r"https?://[^\s\u4e00-\u9fff\u3000-\u303f，。；：、！？（）【】《》\"'<>]+", re.I)

_ROLE_WORDS = (
    "工程师", "经理", "专员", "助理", "主管", "总监", "设计师", "运营", "销售", "顾问",
    "分析师", "实习生", "研究员", "架构师", "测试", "开发", "算法", "产品", "策划",
    "会计", "出纳", "教师", "编辑", "护士", "药师", "技工", "技术员", "文员", "客服",
    "招商", "采购", "物流", "人事", "行政", "法务", "审计", "讲师", "教练", "店长",
)

_COMPANY_SUFFIX = (
    "有限公司", "股份有限公司", "有限责任公司", "集团", "科技", "网络", "信息", "数据",
    "软件", "传媒", "文化", "工作室", "事务所", "研究院", "研究所", "中心", "大学",
    "学院", "学校", "医院", "局", "委员会", "办公室", "协会", "银行", "证券", "保险",
)

_CITIES = (
    "北京", "上海", "天津", "重庆", "广州", "深圳", "杭州", "南京", "苏州", "成都",
    "武汉", "西安", "长沙", "郑州", "济南", "青岛", "合肥", "福州", "厦门", "南昌",
    "沈阳", "大连", "哈尔滨", "长春", "石家庄", "太原", "呼和浩特", "南宁", "海口",
    "贵阳", "昆明", "拉萨", "兰州", "西宁", "银川", "乌鲁木齐", "宁波", "无锡",
    "常州", "佛山", "东莞", "珠海", "中山", "惠州", "温州", "嘉兴", "绍兴", "金华",
    "泉州", "烟台", "潍坊", "洛阳", "襄阳", "宜昌", "徐州", "扬州", "南通", "盐城",
)

_EDUCATION = ("博士", "硕士", "本科", "大专", "专科", "中专", "高中", "学历不限")

# 薪资行必须带明确信号：要么有“薪/待遇/工资”这类字段词，要么是紧贴数字的
# K/千/万/元。不能只看单个 `k`——岗位职责里的 `Workflow` 就自带一个 k，
# 曾经把“2.构建并优化多智能体协作框架…”整句当成了薪资（min=max=2）。
_SALARY_KEYWORD = re.compile(r"薪|待遇|工资|报酬|元/月|元/天|元/时|元每天")
_SALARY_TOKEN = re.compile(
    r"\d[\d,.]*\s*[-~—至到]\s*\d[\d,.]*\s*(?:[kK]|千|万|元)"
    r"|\d[\d,.]*\s*(?:[kK]|千|万)(?![A-Za-z])", re.I)
# 平台默认脱敏展示（BOSS 直聘对求职者显示 **-***元）；这种不该写成数字
_MASKED_SALARY = re.compile(r"[*＊]{2,}\s*[-~—至]\s*[*＊]{2,}\s*(?:[kK]|千|万|元)")
# 语句型内容行：职责描述里经常同时带数字和单位，不能当薪资读
_PROSE_MARKER = re.compile(
    r"职责|任职|要求|负责|参与|构建|设计|优化|实现|开发|搭建|熟悉|熟练|掌握|推进|保障")
_ENUM_PREFIX = re.compile(r"^\s*(?:\d{1,2}[.、)）]|[一二三四五六七八九十]+[、.]|[（(]\d{1,2}[)）])")


@dataclass
class PasteGuess:
    """识别结果。空字符串表示没识别出来，不代表没有。"""

    title: str = ""
    company: str = ""
    city: str = ""
    salary_text: str = ""
    salary_min: int | None = None
    salary_max: int | None = None
    experience: str = ""
    education: str = ""
    url: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title, "company": self.company, "city": self.city,
            "salary_text": self.salary_text, "salary_min": self.salary_min,
            "salary_max": self.salary_max, "experience": self.experience,
            "education": self.education, "url": self.url, "warnings": self.warnings,
        }


def _lines(text: str) -> list[str]:
    return [line.strip(" ·-—|") for line in normalize_text(text).split("\n") if line.strip()]


def _find_url(text: str) -> str:
    match = _URL_RE.search(text)
    return match.group(0).rstrip(".,;:)）】") if match else ""


def _find_title(lines: list[str]) -> str:
    """优先取公告式标题，其次取含职位词的行，最后才拿第一行。

    `招聘单位：某中心` 这类“字段行”不能当标题，所以带冒号的行一律跳过。
    """
    for line in lines[:6]:
        if 6 <= len(line) <= 60 and not _is_field_line(line) \
                and re.search(r"招聘|招录|选调|公告|通知|简章|启事", line):
            return _strip_salary_suffix(line)
    for line in lines[:8]:
        if not (2 <= len(line) <= 40) or _is_field_line(line):
            continue
        if any(word in line for word in _ROLE_WORDS):
            return _strip_salary_suffix(line)
    for line in lines[:3]:
        if 2 <= len(line) <= 40 and not _is_field_line(line) and not line.endswith("招聘"):
            return _strip_salary_suffix(line)
    return ""


# 截图和粘贴里标题与薪资常常挤在同一行：`AI应用开发工程师-JAVA **-***元`
_TITLE_SALARY_SUFFIX = re.compile(
    r"\s*(?:[\d*＊]{1,6}\s*[-~—至]\s*[\d*＊]{1,6}\s*(?:[kK]|千|万|元)(?:\s*[·・]\s*\d{1,2}\s*薪)?"
    r"|面议|薪资面议)\s*$")


def _strip_salary_suffix(line: str) -> str:
    """去掉标题尾巴上的薪资片段，但不把标题清成空字符串。"""
    cleaned = _TITLE_SALARY_SUFFIX.sub("", line).strip(" ·-—|")
    return cleaned or line


def _is_field_line(line: str) -> bool:
    """`岗位职责：` `公司：某公司` 这类字段行。"""
    return bool(re.match(r"^[^：:]{1,8}[:：]", line))


def _find_company(lines: list[str], title: str, text: str) -> str:
    explicit = re.search(r"(?:公司名称|公司|招聘单位|单位名称|所属公司)[:：]\s*([^\n]{2,40})", text)
    if explicit:
        return explicit.group(1).strip(" ·-—")

    for line in lines[:12]:
        if line == title or len(line) > 30 or len(line) < 3:
            continue
        if any(word in line for word in ("岗位职责", "任职要求", "薪资", "福利", "工作地点")):
            continue
        if line.endswith(_COMPANY_SUFFIX):
            return line
    return ""


def _find_city(text: str) -> str:
    explicit = re.search(r"(?:工作地点|工作城市|城市|地点|所在地)[:：]\s*([^\n]{2,20})", text)
    if explicit:
        for city in _CITIES:
            if city in explicit.group(1):
                return city
        return explicit.group(1).split()[0][:10]

    head = text[:600]
    for city in _CITIES:
        if re.search(rf"{city}(?:市)?[·\s\-/、,，]|[·\-\s]{city}(?:市)?(?:$|\s)", head):
            return city
    for city in _CITIES:
        if city in head:
            return city
    return ""


def _salary_candidate(line: str) -> bool:
    """这一行看起来是不是“薪资字段”，而不是职责正文里的一句。"""
    if len(line) > 40 or _ENUM_PREFIX.match(line) or _PROSE_MARKER.search(line):
        return False
    if _MASKED_SALARY.search(line):
        return True
    if _SALARY_KEYWORD.search(line):
        return True
    # 没有字段词时，只接受“短到只剩薪资”的行（如 `20-35K·14薪`）
    return len(line) <= 16 and bool(_SALARY_TOKEN.search(line))


def _find_salary(text: str) -> str:
    """只在像薪资字段的短行里找；解析不出数字就返回空，不写猜出来的值。"""
    for line in _lines(text)[:20]:
        if not _salary_candidate(line) or not re.search(r"\d", line):
            continue
        salary = parse_salary(line)
        if salary.parsed:
            return salary.text
    # 兜底：只为“整段里唯一那个薪资片段”服务，且片段所在行必须是薪资行
    for line in _lines(text)[:20]:
        if not _salary_candidate(line):
            continue
        match = re.search(
            r"\d+(?:\.\d+)?\s*[-~至]\s*\d+(?:\.\d+)?\s*[kK千万]", line)
        if not match:
            continue
        salary = parse_salary(match.group(0))
        if salary.parsed:
            return salary.text
    return ""


def _has_masked_salary(text: str) -> bool:
    """是否有脱敏薪资（`**-***元`）：有的话要提示用户手填，不当作已识别。"""
    return bool(_MASKED_SALARY.search(text[:800]))


def _find_experience(text: str) -> str:
    if re.search(r"经验不限|不限经验", text):
        return "经验不限"
    match = re.search(r"(\d+)\s*[-~至]\s*(\d+)\s*年", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}年"
    match = re.search(r"(\d+)\s*年以上", text)
    return f"{match.group(1)}年以上" if match else ""


def _find_education(text: str) -> str:
    for level in _EDUCATION:
        if level in text:
            return level
    return ""


def analyze(raw: object) -> PasteGuess:
    """识别一段粘贴文本；所有字段都不猜，识别不出来就留空。"""
    text = normalize_text(raw)
    guess = PasteGuess()
    if not text:
        guess.warnings.append("没有可识别的内容")
        return guess

    lines = _lines(text)
    guess.url = _find_url(text)
    guess.title = _find_title(lines)
    guess.company = _find_company(lines, guess.title, text)
    guess.city = _find_city(text)
    guess.salary_text = _find_salary(text)
    if guess.salary_text:
        salary = parse_salary(guess.salary_text)
        guess.salary_min, guess.salary_max = salary.min, salary.max
    guess.experience = _find_experience(text)
    guess.education = _find_education(text)

    _, high = parse_experience(guess.experience)
    if high is None and guess.experience.endswith("年以上"):
        guess.warnings.append("年限只写了「以上」，请确认上限")

    if not guess.title:
        guess.warnings.append("没识别出岗位名，请手动填写")
    if not guess.company:
        guess.warnings.append("没识别出公司名，可手动填写")
    if not guess.salary_text and _has_masked_salary(text):
        guess.warnings.append("薪资被平台脱敏（**-***元），没有具体数字，需要自己填")
    return guess
