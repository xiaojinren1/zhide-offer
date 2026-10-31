"""E2 经历结构化：简历文件/文本 → 结构化经历库。

冷启动决策（设计文档 5.3.1）：只做"上传现有简历自动解析"，不做表单录入。
人工确认：抽取结果必须可编辑（user_confirmed 标记），防错。
"""
from __future__ import annotations

import io
import base64
import re
from pathlib import Path

from core.llm import chat_json, chat_json_multimodal
from engine.models import Experience, ResumeProfile
from engine.suspicion import parse_period
from core.config import agent_rules

_SYSTEM = """你是简历结构化抽取器。把用户简历原文解析成 JSON。
只输出 JSON，字段如下：
{
  "name": "姓名（没有则为空串）",
  "experiences": [
    {
      "kind": "project | internship | education",
      "name": "项目/公司/学校名",
      "role": "角色/职位",
      "period": "原文时间串，如 2024.03-2024.09",
      "actions": ["做的事，逐条"],
      "results": ["结果/产出，逐条"],
      "skills": ["该经历涉及的技能"]
    }
  ],
  "skills": ["技能清单（简历中声明的全部技能）"],
  "education": ["教育经历，逐条"]
}
规则：
1. period 必须逐字保留原文的时间写法，不要改写格式。
2. actions/results 忠于原文，可以合并半句话，但**不许新增原文没有的事实**。
3. 原文没提到的字段给空数组/空串，不许编造。
4. education 类的经历也放进 experiences（kind=education）。"""

_IMAGE_SYSTEM = _SYSTEM + """

你还需要从用户上传的简历截图或照片中读取文字。只根据图片中清晰可见的内容填写字段；
无法辨认的内容留空，不要猜测、补写或根据常识推断。图片中的表格、分栏和项目符号要尽量按原意整理。
"""

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
_IMAGE_MIMES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


def validate_image(content: bytes, filename: str | None = None) -> tuple[str, int, int]:
    """校验并识别图片格式、尺寸；不保存原始图片。"""
    if not content:
        raise ValueError("图片文件为空，请重新选择图片")
    if len(content) > MAX_IMAGE_BYTES:
        raise ValueError("图片超过 10 MB，请压缩图片后重试")
    try:
        from PIL import Image, UnidentifiedImageError
        from PIL.Image import DecompressionBombError, DecompressionBombWarning
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error", DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                image_format = str(image.format or "").upper()
                if image_format not in _IMAGE_MIMES:
                    raise ValueError("暂不支持此图片格式，请上传 JPG、PNG 或 WebP")
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                    raise ValueError("图片像素过大，请压缩图片后重试")
                image.verify()
        return _IMAGE_MIMES[image_format], width, height
    except ValueError:
        raise
    except (UnidentifiedImageError, DecompressionBombError, OSError) as exc:
        raise ValueError("图片无法读取，请上传清晰且未损坏的 JPG、PNG 或 WebP") from exc


def image_data_uri(content: bytes, filename: str | None = None) -> str:
    """将已校验图片转为仅用于本次模型请求的 data URI。"""
    mime, _width, _height = validate_image(content, filename)
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def extract_text(filename: str, content: bytes) -> str:
    """从上传内容提取纯文本。支持 .txt/.md/.pdf/.docx。"""
    suffix = Path(filename or "").suffix.lower()
    if suffix in {".txt", ".md", ""}:
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return content.decode("gbk", errors="replace")
    if suffix == ".pdf":
        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(content)) as pdf:
                return "\n".join((page.extract_text() or "") for page in pdf.pages)
        except Exception as exc:  # pragma: no cover
            raise ValueError(f"PDF 解析失败（请确认已安装 pdfplumber）：{exc}") from exc
    if suffix == ".docx":
        try:
            import docx  # python-docx

            doc = docx.Document(io.BytesIO(content))
            return "\n".join([p.text for p in doc.paragraphs] + [" | ".join(c.text for c in row.cells) for table in doc.tables for row in table.rows])
        except Exception as exc:  # pragma: no cover
            raise ValueError(f"DOCX 解析失败（请确认已安装 python-docx）：{exc}") from exc
    raise ValueError(f"不支持的文件类型：{suffix or '未知'}（支持 txt/md/pdf/docx）")


def _fill_periods(experiences: list[Experience]) -> list[Experience]:
    """用程序补全 start/end（E4 的时间线检测依赖它）。"""
    for e in experiences:
        start, end, _ok = parse_period(e.period or "")
        e.start = start
        e.end = end
    return experiences


def parse_resume(text: str) -> ResumeProfile:
    """解析简历文本 → 结构化经历库。"""
    if not text or not text.strip():
        raise ValueError("简历内容为空")
    data = chat_json(_SYSTEM + agent_rules(), f"简历原文：\n{text}")
    experiences = [
        Experience(
            kind=str(x.get("kind") or "project").strip() or "project",
            name=str(x.get("name") or "").strip(),
            role=str(x.get("role") or "").strip(),
            period=str(x.get("period") or "").strip(),
            actions=[str(a).strip() for a in (x.get("actions") or []) if str(a).strip()],
            results=[str(r).strip() for r in (x.get("results") or []) if str(r).strip()],
            skills=[str(s).strip() for s in (x.get("skills") or []) if str(s).strip()],
        )
        for x in (data.get("experiences") or [])
        if isinstance(x, dict)
    ]
    return ResumeProfile(
        name=str(data.get("name") or "").strip(),
        experiences=_fill_periods(experiences),
        skills=[str(s).strip() for s in (data.get("skills") or []) if str(s).strip()],
        education=[str(s).strip() for s in (data.get("education") or []) if str(s).strip()],
        raw_text=text,
        user_confirmed=False,
    )


def parse_resume_image(content: bytes, filename: str | None = None) -> ResumeProfile:
    """解析简历图片，返回与文本解析一致的未确认 ResumeProfile。"""
    data_uri = image_data_uri(content, filename)
    data = chat_json_multimodal(
        _IMAGE_SYSTEM + agent_rules(),
        "请读取这张简历图片并按约定只输出 JSON。看不清的字段留空。",
        data_uri,
    )
    profile = _profile_from_model_data(data)
    profile.raw_text = f"[图片材料：{filename or '未命名图片'}]"
    profile.user_confirmed = False
    return profile


def _profile_from_model_data(data: dict) -> ResumeProfile:
    """把文本/图片模型返回统一映射为 ResumeProfile。"""
    if not isinstance(data, dict):
        raise ValueError("图片未识别到可用简历内容，请上传更清晰的图片或更换支持视觉输入的模型")
    experiences = [
        Experience(
            kind=str(x.get("kind") or "project").strip() or "project",
            name=str(x.get("name") or "").strip(),
            role=str(x.get("role") or "").strip(),
            period=str(x.get("period") or "").strip(),
            actions=[str(a).strip() for a in (x.get("actions") or []) if str(a).strip()],
            results=[str(r).strip() for r in (x.get("results") or []) if str(r).strip()],
            skills=[str(s).strip() for s in (x.get("skills") or []) if str(s).strip()],
        )
        for x in (data.get("experiences") or [])
        if isinstance(x, dict)
    ]
    name = str(data.get("name") or "").strip()
    skills = [str(s).strip() for s in (data.get("skills") or []) if str(s).strip()]
    education = [str(s).strip() for s in (data.get("education") or []) if str(s).strip()]
    usable_experiences = [
        experience for experience in experiences
        if any([
            experience.name,
            experience.role,
            experience.period,
            experience.actions,
            experience.results,
            experience.skills,
        ])
    ]
    if not (name or skills or education or usable_experiences):
        raise ValueError("图片未识别到可用简历内容，请上传更清晰的图片或更换支持视觉输入的模型")
    return ResumeProfile(
        name=name,
        experiences=_fill_periods(usable_experiences),
        skills=skills,
        education=education,
        raw_text="",
        user_confirmed=False,
    )


def profile_from_dict(data: dict) -> ResumeProfile:
    """前端人工确认后的结构回填（供 /api/quality 等复用，避免重复解析）。"""
    experiences = [
        Experience(
            kind=str(x.get("kind") or "project"),
            name=str(x.get("name") or ""),
            role=str(x.get("role") or ""),
            period=str(x.get("period") or ""),
            actions=list(x.get("actions") or []),
            results=list(x.get("results") or []),
            skills=list(x.get("skills") or []),
        )
        for x in (data.get("experiences") or [])
    ]
    return ResumeProfile(
        name=str(data.get("name") or ""),
        experiences=_fill_periods(experiences),
        skills=list(data.get("skills") or []),
        education=list(data.get("education") or []),
        raw_text=str(data.get("raw_text") or ""),
        user_confirmed=data.get("user_confirmed") is True,
    )
