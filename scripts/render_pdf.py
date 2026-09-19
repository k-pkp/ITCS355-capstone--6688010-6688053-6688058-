"""Render a project Markdown document as a PDF for reading away from a screen.

    python3 scripts/render_pdf.py docs/DESIGN.md
    python3 scripts/render_pdf.py docs/DESIGN-TH.md --thai

Markdown is right for a repository: it diffs, it reviews, it renders on GitHub. It is wrong
for reading a long design on a phone at two in the morning, which is when a design actually
gets read. This renders the same content to A4 without changing a word of it.

Thai needs `--thai`, which switches to a font that has Thai glyphs. Without it every Thai
character renders as an empty box — a failure that looks like a corrupt document rather than
a missing font, which is exactly the kind of quiet wrongness this project is about.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FONT_DIR = PROJECT_ROOT / "docs" / "fonts"

INK = colors.HexColor("#111a21")
INK_SOFT = colors.HexColor("#3c4b57")
MUTED = colors.HexColor("#6b7a87")
ACCENT = colors.HexColor("#0a5f55")
RULE = colors.HexColor("#ccd5dc")
BAND = colors.HexColor("#eef2f5")
QUOTE_BG = colors.HexColor("#fbf0e4")
QUOTE_INK = colors.HexColor("#8f4a10")
CODE_BG = colors.HexColor("#f4f6f8")


def register_thai_fonts() -> tuple[str, str, str]:
    """Load Thai-capable faces, or explain exactly what is missing."""
    regular = FONT_DIR / "NotoSansThai-Regular.ttf"
    bold = FONT_DIR / "NotoSansThai-Bold.ttf"
    for path in (regular, bold):
        if not path.exists():
            raise SystemExit(
                f"missing {path}\n"
                f"Thai text needs a Thai font. Without one every Thai character becomes "
                f"an empty box, which reads as a corrupt file rather than a missing font."
            )

    pdfmetrics.registerFont(TTFont("ThaiBody", str(regular)))
    pdfmetrics.registerFont(TTFont("ThaiBold", str(bold)))
    pdfmetrics.registerFontFamily("ThaiBody", normal="ThaiBody", bold="ThaiBold")

    # Noto Sans Thai has no monospace sibling, and the diagrams in these documents are
    # drawn with box characters that Courier does not carry. DejaVu Sans Mono has them.
    # Code blocks in a Thai document contain Thai words, so they must be set in the Thai
    # face. No monospace font carries both Thai and box-drawing characters, which is why
    # the Thai document draws its diagrams with plain ASCII instead.
    return "ThaiBody", "ThaiBold", "ThaiBody"


# Characters that appear in body text but not in Noto Sans Thai. Each is replaced with the
# closest thing the font can actually draw. Leaving them unmapped is worse than it sounds:
# a missing glyph renders as an empty box, so the reader sees a corrupt document rather
# than a missing font, and nothing in the build reports a problem.
BODY_FONT_SUBSTITUTIONS = {
    "\u2192": "->",       # rightwards arrow
    "\u00b5": "u",        # micro sign, as in ug/m3
    "\u00b3": "3",        # superscript three
}


def substitute_unavailable_characters(text: str) -> str:
    """Replace characters the Thai body font cannot draw with readable stand-ins."""
    for original, replacement in BODY_FONT_SUBSTITUTIONS.items():
        text = text.replace(original, replacement)
    return text


def build_styles(body_font: str, bold_font: str, mono_font: str) -> dict:
    """Return every paragraph style the renderer uses."""
    base = getSampleStyleSheet()["BodyText"]
    thai = body_font != "Helvetica"
    leading = 17.5 if thai else 14.6

    styles = {
        "h1": ParagraphStyle("H1", parent=base, fontName=bold_font, fontSize=19,
                             leading=leading + 8, textColor=INK, spaceAfter=3 * mm),
        "h2": ParagraphStyle("H2", parent=base, fontName=bold_font, fontSize=14,
                             leading=leading + 4, textColor=INK,
                             spaceBefore=7 * mm, spaceAfter=2.5 * mm),
        "h3": ParagraphStyle("H3", parent=base, fontName=bold_font, fontSize=11.5,
                             leading=leading + 1, textColor=ACCENT,
                             spaceBefore=5.5 * mm, spaceAfter=2 * mm),
        "body": ParagraphStyle("Body", parent=base, fontName=body_font, fontSize=9.8,
                               leading=leading, textColor=INK_SOFT, spaceAfter=2.8 * mm),
        "quote": ParagraphStyle("Quote", parent=base, fontName=body_font, fontSize=9.3,
                                leading=leading - 0.5, textColor=QUOTE_INK),
        "cell": ParagraphStyle("Cell", parent=base, fontName=body_font, fontSize=8.5,
                               leading=leading - 3, textColor=INK_SOFT),
        "code": ParagraphStyle("Code", parent=base, fontName=mono_font, fontSize=7.2,
                               leading=8.8, textColor=INK),
    }
    styles["cell_head"] = ParagraphStyle("CellHead", parent=styles["cell"],
                                         fontName=bold_font, textColor=INK)
    styles["bullet"] = ParagraphStyle("Bullet", parent=styles["body"],
                                      leftIndent=6 * mm, bulletIndent=1.5 * mm,
                                      spaceAfter=1.8 * mm)
    return styles


def to_inline_markup(text: str, mono_font: str, substitute: bool = False) -> str:
    """Convert inline Markdown to reportlab markup."""
    if substitute:
        text = substitute_unavailable_characters(text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)          # links: keep the label
    text = re.sub(r"~~(.+?)~~", r"<strike>\1</strike>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"`([^`]+)`",
                  rf'<font face="{mono_font}" size="8.4">\1</font>', text)
    return text


def make_table(rows: list[list[str]], styles: dict, mono_font: str,
               substitute: bool = False) -> Table:
    """Render one Markdown table, sized to the text column."""
    available = 174 * mm
    column_count = max(len(row) for row in rows)
    widths = [available / column_count] * column_count

    formatted = []
    for index, row in enumerate(rows):
        padded = row + [""] * (column_count - len(row))
        style = styles["cell_head"] if index == 0 else styles["cell"]
        formatted.append([Paragraph(to_inline_markup(cell, mono_font, substitute), style)
                          for cell in padded])

    table = Table(formatted, colWidths=widths, hAlign="LEFT", repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BAND),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    return table


def make_quote(lines: list[str], styles: dict, mono_font: str,
               substitute: bool = False) -> Table:
    """Render a blockquote as a tinted panel."""
    paragraph = Paragraph(to_inline_markup(" ".join(lines), mono_font, substitute),
                          styles["quote"])
    table = Table([[paragraph]], colWidths=[174 * mm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), QUOTE_BG),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def make_code_block(lines: list[str], styles: dict) -> Table:
    """Render a fenced code block, keeping its alignment intact."""
    block = Preformatted("\n".join(lines), styles["code"])
    table = Table([[block]], colWidths=[174 * mm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def parse_markdown(source: str, styles: dict, mono_font: str,
                   substitute: bool = False) -> list:
    """Turn the document into flowables, in order."""
    flowables: list = []
    lines = source.splitlines()
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith("```"):
            index += 1
            block: list[str] = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                block.append(lines[index])
                index += 1
            index += 1
            flowables.append(make_code_block(block, styles))
            flowables.append(Spacer(1, 3 * mm))
            continue

        if not stripped or set(stripped) <= set("-*_ ") and len(stripped) >= 3:
            index += 1
            continue

        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            key = {1: "h1", 2: "h2"}.get(level, "h3")
            flowables.append(Paragraph(
                to_inline_markup(stripped.lstrip("#").strip(), mono_font, substitute), styles[key]))
            index += 1
            continue

        if stripped.startswith(">"):
            quote_lines = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote_lines.append(lines[index].strip().lstrip(">").strip())
                index += 1
            flowables.append(make_quote(quote_lines, styles, mono_font, substitute))
            flowables.append(Spacer(1, 3 * mm))
            continue

        if stripped.startswith("|"):
            table_rows = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                cells = [cell.strip()
                         for cell in lines[index].strip().strip("|").split("|")]
                is_separator = all(set(cell) <= set("-: ") and cell for cell in cells)
                if not is_separator:
                    table_rows.append(cells)
                index += 1
            if table_rows:
                flowables.append(KeepTogether(make_table(table_rows, styles, mono_font, substitute)))
                flowables.append(Spacer(1, 3 * mm))
            continue

        bullet_match = re.match(r"^([-*]|\d+\.)\s+(.*)", stripped)
        if bullet_match:
            item_lines = [bullet_match.group(2)]
            index += 1
            while index < len(lines):
                follow = lines[index]
                if (not follow.strip() or re.match(r"^\s*([-*]|\d+\.)\s+", follow)
                        or follow.strip().startswith(("#", "|", "```", ">"))):
                    break
                item_lines.append(follow.strip())
                index += 1
            marker = "•" if bullet_match.group(1) in "-*" else bullet_match.group(1)
            flowables.append(Paragraph(
                to_inline_markup(" ".join(item_lines), mono_font, substitute),
                styles["bullet"], bulletText=marker))
            continue

        paragraph_lines = []
        while index < len(lines):
            current = lines[index].strip()
            if (not current or current.startswith(("#", "|", "```", ">"))
                    or re.match(r"^([-*]|\d+\.)\s+", current)):
                break
            paragraph_lines.append(current)
            index += 1

        flowables.append(Paragraph(
            to_inline_markup(" ".join(paragraph_lines), mono_font, substitute),
            styles["body"]))

    return flowables


def make_page_furniture(header: str, body_font: str):
    """Return the callback that draws the running header and page number."""

    def draw(canvas, document) -> None:
        """Draw the running header, the rule beneath it, and the page number."""
        canvas.saveState()
        canvas.setFont(body_font, 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, A4[1] - 12 * mm, header)
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.4)
        canvas.line(18 * mm, A4[1] - 14 * mm, A4[0] - 18 * mm, A4[1] - 14 * mm)
        canvas.drawCentredString(A4[0] / 2, 12 * mm, str(document.page))
        canvas.restoreState()

    return draw


def parse_command_line() -> argparse.Namespace:
    """Command line for the renderer."""
    parser = argparse.ArgumentParser(description="Render a Markdown document as a PDF")
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path, default=None,
                        help="defaults to the source path with a .pdf suffix")
    parser.add_argument("--thai", action="store_true",
                        help="use a font with Thai glyphs")
    parser.add_argument("--header", default=None,
                        help="running header; defaults to the file name")
    return parser.parse_args()


def main() -> int:
    """Render the document and report where it landed."""
    options = parse_command_line()
    if not options.source.exists():
        raise SystemExit(f"{options.source} not found")

    if options.thai:
        body_font, bold_font, mono_font = register_thai_fonts()
    else:
        body_font, bold_font, mono_font = "Helvetica", "Helvetica-Bold", "Courier"

    styles = build_styles(body_font, bold_font, mono_font)
    destination = options.out or options.source.with_suffix(".pdf")
    header = options.header or options.source.stem

    document = SimpleDocTemplate(
        str(destination), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=20 * mm, bottomMargin=18 * mm,
        title=options.source.stem,
    )
    draw = make_page_furniture(header, body_font)
    flowables = parse_markdown(options.source.read_text(), styles, mono_font,
                               substitute=options.thai)
    document.build(flowables, onFirstPage=draw, onLaterPages=draw)

    print(f"wrote {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
