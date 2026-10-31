"""Authenticated, stateless Markdown-to-DOCX export; never reads paths or URLs."""
from __future__ import annotations

import re
import html
import os
from pathlib import Path
from io import BytesIO
from urllib.parse import quote

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from core import accounts

router = APIRouter(prefix="/api/export", tags=["export"], dependencies=[
    Depends(accounts.require_user), Depends(accounts.require_csrf),
])
MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_PDF = "application/pdf"


class ExportRequest(BaseModel):
    markdown: str = Field(min_length=1, max_length=100_000)
    name: str = Field(default="职得offer", max_length=200)

    @field_validator("markdown", "name", mode="before")
    @classmethod
    def valid_markdown(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        if not value.strip():
            raise ValueError("简历正文不能为空")
        if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", value):
            raise HTTPException(status_code=422, detail="简历正文包含不支持的控制字符")
        return value


def _inline(paragraph, text: str) -> None:
    # Only display link labels; do not create relationships to remote targets.
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    for part in re.split(r"(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\*[^*]+\*)", text):
        if not part:
            continue
        bold = (part.startswith("**") and part.endswith("**")) or (part.startswith("__") and part.endswith("__"))
        code = part.startswith("`") and part.endswith("`")
        italic = not bold and part.startswith("*") and part.endswith("*")
        run = paragraph.add_run(part[2:-2] if bold else part[1:-1] if code or italic else part)
        run.bold, run.italic = bold, italic
        if code:
            run.font.name = "Consolas"


def build_docx(markdown: str) -> BytesIO:
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin = section.bottom_margin = Cm(1.8)
    section.left_margin = section.right_margin = Cm(2)
    for name in ("Normal", "Title", "Heading 1", "Heading 2", "Heading 3", "List Bullet", "List Number"):
        style = document.styles[name]
        style.font.name = "Microsoft YaHei"
        style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        style.font.color.rgb = RGBColor.from_string("183252")
    normal = document.styles["Normal"]
    normal.font.size = Pt(10.5)
    normal.paragraph_format.space_after = Pt(5)
    normal.paragraph_format.line_spacing = 1.15
    fenced = False
    for line in markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            fenced = not fenced
            continue
        if not stripped:
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        bullet = re.match(r"^[-*+]\s+(.+)$", stripped)
        numbered = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        if fenced:
            document.add_paragraph(line)
        elif re.fullmatch(r"([-*_])(?:\s*\1){2,}", stripped):
            p = document.add_paragraph()
            border = OxmlElement("w:pBdr")
            bottom = OxmlElement("w:bottom")
            for key, value in (("val", "single"), ("sz", "4"), ("color", "D7E3F4")):
                bottom.set(qn(f"w:{key}"), value)
            border.append(bottom)
            p._p.get_or_add_pPr().append(border)
        elif heading:
            p = document.add_paragraph(style=f"Heading {min(len(heading[1]), 3)}")
            _inline(p, heading[2])
        elif bullet or numbered:
            match = bullet or numbered
            _inline(document.add_paragraph(style="List Bullet" if bullet else "List Number"), match[1])
        else:
            _inline(document.add_paragraph(), stripped)
    output = BytesIO()
    document.save(output)
    output.seek(0)
    return output


def _pdf_font_path() -> Path:
    candidates = []
    configured = os.environ.get("JOBAGENT_PDF_FONT", "").strip()
    if configured:
        candidates.append(Path(configured))
    candidates.extend([
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    ])
    for path in candidates:
        if path.is_file():
            return path
    raise HTTPException(status_code=503, detail="PDF 导出缺少可用的中文字体，请配置 JOBAGENT_PDF_FONT 后重试")


def _pdf_inline(text: str) -> str:
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*([^*]+)\*\*|__([^_]+)__", lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = re.sub(r"`([^`]+)`", r"<font name=\"JobAgentMono\">\1</font>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
    return text


def build_pdf(markdown: str) -> BytesIO:
    try:
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import HRFlowable, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer
    except ImportError as exc:  # pragma: no cover - dependency is pinned in requirements
        raise HTTPException(status_code=503, detail="PDF 导出依赖未安装，请先安装 backend/requirements.txt") from exc

    font_path = _pdf_font_path()
    try:
        pdfmetrics.registerFont(TTFont("JobAgentCJK", str(font_path)))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="PDF 导出字体无法加载，请检查 JOBAGENT_PDF_FONT") from exc

    styles = getSampleStyleSheet()
    normal = ParagraphStyle("JobAgentNormal", parent=styles["Normal"], fontName="JobAgentCJK", fontSize=10.5,
                            leading=16, spaceAfter=5, alignment=TA_LEFT, wordWrap="CJK")
    heading = {
        1: ParagraphStyle("JobAgentH1", parent=normal, fontSize=18, leading=24, spaceBefore=8, spaceAfter=10),
        2: ParagraphStyle("JobAgentH2", parent=normal, fontSize=14, leading=20, spaceBefore=7, spaceAfter=7),
        3: ParagraphStyle("JobAgentH3", parent=normal, fontSize=11.5, leading=17, spaceBefore=6, spaceAfter=5),
    }
    mono = ParagraphStyle("JobAgentMono", parent=normal, fontName="JobAgentCJK", fontSize=9.5, leading=14,
                          leftIndent=5, textColor="#4f6075")
    story = []
    fenced = False
    bullet_items = []
    numbered_items = []

    def flush_lists():
        nonlocal bullet_items, numbered_items
        if bullet_items:
            story.append(ListFlowable([ListItem(Paragraph(item, normal)) for item in bullet_items], bulletType="bullet", leftIndent=14))
            story.append(Spacer(1, 2 * mm))
            bullet_items = []
        if numbered_items:
            story.append(ListFlowable([ListItem(Paragraph(item, normal)) for item in numbered_items], bulletType="1", leftIndent=14))
            story.append(Spacer(1, 2 * mm))
            numbered_items = []

    for line in markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_lists()
            fenced = not fenced
            continue
        if not stripped:
            continue
        if fenced:
            story.append(Paragraph(_pdf_inline(line), mono))
            continue
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        bullet_match = re.match(r"^[-*+]\s+(.+)$", stripped)
        numbered_match = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        if heading_match:
            flush_lists()
            level = min(len(heading_match.group(1)), 3)
            story.append(Paragraph(_pdf_inline(heading_match.group(2)), heading[level]))
        elif bullet_match:
            numbered_items and flush_lists()
            bullet_items.append(_pdf_inline(bullet_match.group(1)))
        elif numbered_match:
            bullet_items and flush_lists()
            numbered_items.append(_pdf_inline(numbered_match.group(1)))
        elif re.fullmatch(r"([-*_])(?:\s*\1){2,}", stripped):
            flush_lists()
            story.append(HRFlowable(width="100%", thickness=0.6, color="#D7E3F4", spaceBefore=4, spaceAfter=7))
        else:
            flush_lists()
            story.append(Paragraph(_pdf_inline(stripped), normal))
    flush_lists()

    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, rightMargin=20 * mm, leftMargin=20 * mm,
                                 topMargin=18 * mm, bottomMargin=18 * mm, title="职得offer 定向简历")
    document.build(story)
    output.seek(0)
    return output


def _safe_filename(name: str, extension: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f\ud800-\udfff\ufffe\uffff]', "-", name).strip().rstrip(". ")[:80] or "职得offer"
    return quote(f"{safe}-定向简历.{extension}", safe="")


@router.post("/docx")
def export_docx(request: ExportRequest):
    filename = _safe_filename(request.name, "docx")
    return StreamingResponse(build_docx(request.markdown), media_type=MIME, headers={
        "Content-Disposition": f"attachment; filename=resume.docx; filename*=UTF-8''{filename}",
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })


@router.post("/pdf")
def export_pdf(request: ExportRequest):
    filename = _safe_filename(request.name, "pdf")
    return StreamingResponse(build_pdf(request.markdown), media_type=MIME_PDF, headers={
        "Content-Disposition": f"attachment; filename=resume.pdf; filename*=UTF-8''{filename}",
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })
