"""Render one of the willab prompt docs to a readable PDF.

Deliberately narrow: it handles the markdown these docs actually use —
headings, paragraphs, bullet/numbered lists, blockquotes, fenced code, pipe
tables, horizontal rules, `inline code` and **bold**. Nothing else.

Fonts are DejaVu (registered as TrueType), not reportlab's built-in Type1
faces: the documents carry -> X * >= <-> style arrows and glyphs that the
built-ins' WinAnsi encoding lacks, and a missing glyph renders as a solid
black box rather than failing loudly.

The hard part is inline code. A span like `**...**` or `{{orange:...}}` is
CONTENT in these docs, so code spans are lifted out to placeholders before any
bold/XML processing and restored afterwards — otherwise the renderer eats the
very syntax the document is about.
"""
from __future__ import annotations

import re
import sys
from html import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (HRFlowable, KeepTogether, Paragraph,
                                SimpleDocTemplate, Spacer, Table,
                                TableStyle)

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
BODY, BODY_B, MONO, MONO_B = "DJV", "DJV-B", "DJVM", "DJVM-B"

INK = colors.HexColor("#111214")
MUTED = colors.HexColor("#6b7280")
ACCENT = colors.HexColor("#d9480f")
RULE = colors.HexColor("#e5e7eb")
CODE_BG = colors.HexColor("#f6f7f9")
HEAD_BG = colors.HexColor("#f0f1f3")

MARGIN = 16 * mm
AVAIL = A4[0] - 2 * MARGIN

_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
# single-asterisk italics, run AFTER bold has consumed every ** pair
_ITAL = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_SENTINEL = "\x00CODE%d\x00"


def register_fonts():
    for name, fn in ((BODY, "DejaVuSans.ttf"), (BODY_B, "DejaVuSans-Bold.ttf"),
                     (MONO, "DejaVuSansMono.ttf"),
                     (MONO_B, "DejaVuSansMono-Bold.ttf")):
        pdfmetrics.registerFont(TTFont(name, f"{FONT_DIR}/{fn}"))
    pdfmetrics.registerFontFamily(BODY, normal=BODY, bold=BODY_B,
                                  italic=BODY, boldItalic=BODY_B)


def inline(text: str, *, code_size: int = 8) -> str:
    """Markdown inline → reportlab markup. Code spans are lifted FIRST so their
    contents (which in these docs include ** and {{ }}) are never reparsed."""
    spans: list[str] = []

    def _stash(m):
        # a table cell escapes its pipes as \| — unescape INSIDE the code span
        # too, or the grammar table prints `<snippet_id>\|<take_session_id>`
        spans.append(m.group(1).replace("\\|", "|"))
        return _SENTINEL % (len(spans) - 1)

    text = _CODE.sub(_stash, text)
    text = text.replace("\\|", "|")
    text = escape(text, quote=False)
    text = _LINK.sub(r"\1", text)
    text = _BOLD.sub(r"<b>\1</b>", text)
    text = _ITAL.sub(r"<i>\1</i>", text)
    for i, raw in enumerate(spans):
        text = text.replace(
            _SENTINEL % i,
            f'<font face="{MONO}" size="{code_size}" '
            f'color="#8a3b12">{escape(raw, quote=False)}</font>')
    return text


def styles():
    ss = getSampleStyleSheet()

    def mk(name, **kw):
        kw.setdefault("fontName", BODY)
        kw.setdefault("textColor", INK)
        kw.setdefault("alignment", TA_LEFT)
        return ParagraphStyle(name, parent=ss["BodyText"], **kw)

    return {
        "h1": mk("h1", fontName=BODY_B, fontSize=19, leading=24,
                 spaceBefore=2, spaceAfter=10),
        "h2": mk("h2", fontName=BODY_B, fontSize=13.5, leading=18,
                 spaceBefore=18, spaceAfter=6),
        "h3": mk("h3", fontName=BODY_B, fontSize=11, leading=15,
                 spaceBefore=13, spaceAfter=4),
        "body": mk("body", fontSize=9.5, leading=14.5, spaceAfter=7),
        # bulletIndent/leftIndent are what keep a wrapped second line aligned
        # under the first word rather than under the bullet.
        "li": mk("li", fontSize=9.5, leading=14.5, spaceAfter=4,
                 leftIndent=15, bulletIndent=3, bulletFontName=BODY,
                 bulletFontSize=9.5),
        "quote": mk("quote", fontSize=9.5, leading=14.5, spaceAfter=7,
                    leftIndent=10, textColor=colors.HexColor("#3f4450"),
                    borderPadding=0),
        "code": mk("code", fontName=MONO, fontSize=8, leading=11.5,
                   spaceAfter=0, textColor=colors.HexColor("#20242c")),
        "th": mk("th", fontName=BODY_B, fontSize=8.5, leading=12,
                 spaceAfter=0),
        "td": mk("td", fontSize=8.5, leading=12, spaceAfter=0),
        "foot": mk("foot", fontSize=8, leading=11, textColor=MUTED),
    }


def parse_table(lines: list[str]) -> list[list[str]]:
    rows = []
    for ln in lines:
        cells = re.split(r"(?<!\\)\|", ln.strip())
        if cells and not cells[0].strip():
            cells = cells[1:]
        if cells and not cells[-1].strip():
            cells = cells[:-1]
        if all(re.fullmatch(r"\s*:?-{2,}:?\s*", c) for c in cells):
            continue                                   # the --- separator row
        rows.append([c.strip() for c in cells])
    return rows


def build_table(rows, st):
    if not rows:
        return None
    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    # Column widths track content weight, with a floor so a narrow column
    # ("#", a verdict) never collapses to an unreadable ribbon.
    weights = []
    for c in range(ncols):
        longest = max(len(r[c]) for r in rows)
        weights.append(max(longest, 6) ** 0.75)
    total = sum(weights)
    widths = [max(AVAIL * w / total, 14 * mm) for w in weights]
    if sum(widths) > AVAIL:                            # re-normalise the floors
        widths = [w * AVAIL / sum(widths) for w in widths]

    data = [[Paragraph(inline(c, code_size=7.5),
                       st["th"] if i == 0 else st["td"]) for c in row]
            for i, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#c9ccd2")),
        ("GRID", (0, 0), (-1, -1), 0.3, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def code_block(lines, st):
    body = "<br/>".join(
        escape(ln, quote=False).replace(" ", "&nbsp;") or "&nbsp;"
        for ln in lines)
    cell = Paragraph(body, st["code"])
    t = Table([[cell]], colWidths=[AVAIL], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
        ("BOX", (0, 0), (-1, -1), 0.3, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def convert(md: str, st) -> list:
    flow: list = []
    lines = md.split("\n")
    i, n = 0, len(lines)
    pending: list[str] = []
    bullets: list = []

    def flush_para():
        nonlocal pending
        if pending:
            flow.append(Paragraph(inline(" ".join(pending)), st["body"]))
            pending = []

    def flush_list():
        """Each item is a Paragraph carrying its own bulletText — ListFlowable
        drew the literal word "bullet" over the first item's text."""
        nonlocal bullets
        if bullets:
            for mark, text in bullets:
                flow.append(Paragraph(inline(text), st["li"], bulletText=mark))
            flow.append(Spacer(1, 4))
            bullets = []

    while i < n:
        ln = lines[i]
        stripped = ln.strip()

        if stripped.startswith("```"):
            flush_para(); flush_list()
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            flow.append(Spacer(1, 3))
            flow.append(code_block(buf, st))
            flow.append(Spacer(1, 9))
            continue

        if stripped.startswith("|") and "|" in stripped[1:]:
            flush_para(); flush_list()
            buf = []
            while i < n and lines[i].strip().startswith("|"):
                buf.append(lines[i])
                i += 1
            t = build_table(parse_table(buf), st)
            if t is not None:
                flow.append(Spacer(1, 3))
                flow.append(t)
                flow.append(Spacer(1, 10))
            continue

        if not stripped:
            flush_para(); flush_list()
            i += 1
            continue

        if re.fullmatch(r"-{3,}", stripped):
            flush_para(); flush_list()
            flow.append(Spacer(1, 5))
            flow.append(HRFlowable(width="100%", thickness=0.5, color=RULE))
            flow.append(Spacer(1, 5))
            i += 1
            continue

        m = re.match(r"(#{1,6})\s+(.*)", stripped)
        if m:
            flush_para(); flush_list()
            lvl = len(m.group(1))
            key = "h1" if lvl == 1 else ("h2" if lvl == 2 else "h3")
            para = Paragraph(inline(m.group(2)), st[key])
            # A heading never lands alone at the foot of a page.
            flow.append(para if lvl == 1 else KeepTogether([para, Spacer(1, 1)]))
            i += 1
            continue

        if stripped.startswith(">"):
            flush_para(); flush_list()
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            text = " ".join(x for x in buf if x)
            para = Paragraph(inline(text), st["quote"])
            t = Table([[para]], colWidths=[AVAIL], hAlign="LEFT")
            t.setStyle(TableStyle([
                ("LINEBEFORE", (0, 0), (0, -1), 2, ACCENT),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            flow.append(Spacer(1, 2))
            flow.append(t)
            flow.append(Spacer(1, 9))
            continue

        m_ul = re.match(r"[-*]\s+(.*)", stripped)
        m_ol = re.match(r"(\d+)\.\s+(.*)", stripped)
        if m_ul or m_ol:
            flush_para()
            # an ordered item keeps its NUMBER as the bullet — these docs use
            # numbered lists for ordered rules ("1. Flat, not nested")
            mark = "•" if m_ul else f"{m_ol.group(1)}."
            text = m_ul.group(1) if m_ul else m_ol.group(2)
            i += 1
            # a continuation line is indented and not itself a new block
            while (i < n and lines[i].strip()
                   and (lines[i].startswith("  ") or lines[i].startswith("\t"))
                   and not re.match(r"\s*([-*]\s|\d+\.\s|\||```|#)",
                                    lines[i])):
                text += " " + lines[i].strip()
                i += 1
            bullets.append((mark, text))
            continue

        flush_list()
        pending.append(stripped)
        i += 1

    flush_para()
    flush_list()
    return flow


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(BODY, 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, 10 * mm, doc.title)
    canvas.drawRightString(A4[0] - MARGIN, 10 * mm, str(canvas.getPageNumber()))
    canvas.restoreState()


def main(src: str, dst: str, title: str):
    register_fonts()
    st = styles()
    md = open(src, encoding="utf-8").read()
    doc = SimpleDocTemplate(
        dst, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=18 * mm,
        title=title, author="WillpowerLab")
    doc.build(convert(md, st), onFirstPage=footer, onLaterPages=footer)
    print(f"wrote {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2],
         sys.argv[3] if len(sys.argv) > 3 else "WillpowerLab")
