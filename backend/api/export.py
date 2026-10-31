"""Authenticated, stateless Markdown-to-DOCX export; never reads paths or URLs."""
from __future__ import annotations

import re
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


@router.post("/docx")
def export_docx(request: ExportRequest):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f\ud800-\udfff\ufffe\uffff]', "-", request.name).strip().rstrip(". ")[:80] or "职得offer"
    filename = quote(f"{name}-定向简历.docx", safe="")
    return StreamingResponse(build_docx(request.markdown), media_type=MIME, headers={
        "Content-Disposition": f"attachment; filename=resume.docx; filename*=UTF-8''{filename}",
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })
