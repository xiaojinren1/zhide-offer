"""Read layout signals from reference documents without importing their content."""
from io import BytesIO
from threading import Lock
from zipfile import ZipFile

import pdfplumber
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

_pdf_render_lock = Lock()


def pdf_first_page(content: bytes) -> bytes:
    with _pdf_render_lock, pdfplumber.open(BytesIO(content)) as pdf:
        if not pdf.pages:
            raise ValueError("PDF 没有可识别的页面")
        page = pdf.pages[0]
        if not 0 < max(page.width, page.height) <= 10_000:
            raise ValueError("PDF 页面尺寸不受支持")
        resolution = min(160, 72 * 1600 / max(page.width, page.height))
        image = page.to_image(resolution=resolution).original
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()


def _paragraph_style(paragraph, getter):
    for run in paragraph.runs:
        if run.text.strip():
            value = getter(run)
            if value is not None:
                return value
    style = paragraph.style
    while style is not None:
        value = getter(style)
        if value is not None:
            return value
        style = style.base_style
    return None


def docx_layout(content: bytes) -> dict:
    with ZipFile(BytesIO(content)) as archive:
        if sum(entry.file_size for entry in archive.infolist()) > 40 * 1024 * 1024:
            raise ValueError("Word 文档解压后过大")
    document = Document(BytesIO(content))
    paragraphs = [paragraph for paragraph in document.paragraphs if paragraph.text.strip()]
    tables = document.tables
    first_table = tables[0] if tables else None
    cells = first_table.rows[0].cells if first_table and first_table.rows else ()
    title = paragraphs[0] if paragraphs else None
    header_style = "standard"
    sidebar_side = "left"
    template = "classic"
    if len(cells) == 2 and cells[0]._tc is not cells[1]._tc:
        left, right = cells
        if any(right._tc.iter(qn("w:drawing"))) and not right.text.strip():
            header_style = "portrait"
            title = next((p for p in left.paragraphs if p.text.strip()), title)
        elif left.text.strip() and right.text.strip() and left.width and right.width:
            if min(left.width, right.width) / max(left.width, right.width) < .75:
                template = "sidebar"
                sidebar_side = "left" if left.width < right.width else "right"
                title = next((p for p in cells[0 if sidebar_side == "left" else 1].paragraphs if p.text.strip()), title)
        paragraphs += [p for row in first_table.rows for cell in row.cells for p in cell.paragraphs if p.text.strip()]
    if not paragraphs:
        raise ValueError("Word 文档没有可识别的段落")

    heading = next((p for p in paragraphs if p is not title and p.style.name.lower().startswith("heading")), None)
    normal = document.styles["Normal"]
    size = normal.font.size
    spacing = normal.paragraph_format.line_spacing
    font_size = min((13, 14, 16), key=lambda value: abs(value - size.pt / .75)) if size else 14
    line_spacing = min((1.35, 1.6, 1.85), key=lambda value: abs(value - spacing)) if type(spacing) is float else 1.6
    if template == "classic" and line_spacing == 1.35 and font_size <= 14:
        template = "compact"

    def color(paragraph):
        value = _paragraph_style(paragraph, lambda source: source.font.color.rgb) if paragraph else None
        return f"#{value}" if value else None

    title_font = _paragraph_style(title, lambda source: source.font.name) if title else None
    background = document.element.find(qn("w:background"))
    paper = background.get(qn("w:color"), "") if background is not None else ""
    if len(paper) != 6 or any(char not in "0123456789abcdefABCDEF" for char in paper):
        paper = "ffffff"
    return {
        "template": template, "background": "#edf2f8", "paper": f"#{paper}",
        "accent": color(heading) or "#254264", "nameColor": color(title),
        "fontSize": font_size, "spacing": line_spacing,
        "headerAlign": "center" if title and (title.alignment or title.style.paragraph_format.alignment) == WD_ALIGN_PARAGRAPH.CENTER else "left",
        "sidebarSide": sidebar_side, "headerStyle": header_style,
        "headingFont": "serif" if title_font and title_font.casefold() in {"simsun", "宋体", "songti sc", "times new roman"} else "sans",
    }


def markdown_layout(content: bytes) -> dict:
    text = content.decode("utf-8-sig")
    lines = text.splitlines()
    nonempty = sum(bool(line.strip()) for line in lines)
    if not nonempty:
        raise ValueError("Markdown 文档为空")
    compact = nonempty >= 5 and nonempty / len(lines) >= .8
    return {
        "template": "compact" if compact else "classic", "background": "#edf2f8",
        "paper": "#ffffff", "accent": "#254264", "fontSize": 14, "spacing": 1.35 if compact else 1.6,
    }
