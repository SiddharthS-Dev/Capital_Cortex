"""asset_generator (FR-05): the 8 artefacts, rendered from citation-checked sections.

One document model feeds every renderer. Each claim carries numbered citation markers [n]; every artefact ends
with an evidence appendix mapping n → ref → what the record is and where it came from. Gaps render as
highlighted ``[EVIDENCE REQUIRED: …]`` blocks (or ``[EVIDENCE WAIVED: …]`` with the waiving Admin and reason).

Formats: docx (python-docx), pptx (python-pptx), xlsx (openpyxl; the financial model and budget use live Excel
formulas, never pasted results), pdf (WeasyPrint over the same HTML as the in-app preview) — one Python runtime
(R8).
"""

from __future__ import annotations

import html
import io
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

MARK = re.compile(r"\s+$")
YELLOW = "FFF2CC"


# ----------------------------------------------------------------------------- document model
@dataclass
class Item:
    text: str
    marks: list[int]


@dataclass
class Section:
    key: str
    title: str
    items: list[Item] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    waived: list[str] = field(default_factory=list)


@dataclass
class Appendix:
    n: int
    ref: str
    label: str
    source: str


@dataclass
class DocModel:
    title: str
    subtitle: str
    artefact: str
    sections: list[Section]
    appendix: list[Appendix]
    meta: dict[str, Any]
    disclaimer: str = ""

    @property
    def gap_count(self) -> int:
        return sum(len(s.gaps) for s in self.sections)


def build_model(
    *,
    title: str,
    subtitle: str,
    artefact: str,
    sections: list[dict[str, Any]],
    ref_labels: dict[str, tuple[str, str]],
    waivers: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
    disclaimer: str = "",
) -> DocModel:
    """``sections``: [{key, title, claims: [{text, evidence, basis}], gaps: [{id, text}]}]; numbering by first use."""
    waived = {(w["section"], w["gap_id"]): w for w in (waivers or [])}
    numbers: dict[str, int] = {}
    out: list[Section] = []
    for s in sections:
        sec = Section(s["key"], s["title"])
        for c in s.get("claims") or []:
            refs = list(dict.fromkeys((c.get("evidence") or []) + (c.get("basis") or [])))
            marks = [numbers.setdefault(r, len(numbers) + 1) for r in refs]
            sec.items.append(Item(c["text"], marks))
        for g in s.get("gaps") or []:
            w = waived.get((s["key"], g["id"]))
            if w:
                sec.waived.append(f"{g['text']} — waived by {w['by']}: {w['reason']}")
            else:
                sec.gaps.append(g["text"])
        out.append(sec)
    appendix = [
        Appendix(n, r, *(ref_labels.get(r) or (r.split(":")[0].replace("_", " "), "")))
        for r, n in sorted(numbers.items(), key=lambda kv: kv[1])
    ]
    return DocModel(title, subtitle, artefact, out, appendix, meta or {}, disclaimer)


def marks_text(item: Item) -> str:
    return item.text + (" " + "".join(f"[{m}]" for m in item.marks) if item.marks else "")


# ----------------------------------------------------------------------------- HTML (preview + PDF)
CSS = """
@page { size: A4; margin: 18mm 16mm; @bottom-right { content: counter(page) " / " counter(pages); font-size: 8pt; color: #666; } }
body { font-family: 'DejaVu Sans', Arial, sans-serif; font-size: 10pt; color: #1f2937; line-height: 1.45; }
h1 { font-size: 20pt; margin: 0 0 4pt; } .sub { color: #6b7280; margin-bottom: 14pt; }
h2 { font-size: 13pt; border-bottom: 1px solid #e5e7eb; padding-bottom: 2pt; margin-top: 16pt; }
sup { color: #1d4ed8; font-size: 7pt; } .gap { background: #fff2cc; border-left: 3pt solid #d97706; padding: 3pt 6pt;
margin: 4pt 0; font-weight: bold; } .waived { background: #f3f4f6; border-left: 3pt solid #9ca3af; padding: 3pt 6pt; margin: 4pt 0; }
table { border-collapse: collapse; width: 100%; font-size: 8pt; } td, th { border: 1px solid #e5e7eb; padding: 2pt 4pt; vertical-align: top; }
.disclaimer { margin-top: 18pt; font-size: 8pt; color: #6b7280; } .meta { font-size: 8pt; color: #6b7280; }
"""


def render_html(m: DocModel) -> str:
    e = html.escape
    parts = [f"<html><head><meta charset='utf-8'><title>{e(m.title)}</title><style>{CSS}</style></head><body>",
             f"<h1>{e(m.title)}</h1><div class='sub'>{e(m.subtitle)}</div>"]  # fmt: skip
    for s in m.sections:
        parts.append(f"<h2>{e(s.title)}</h2>")
        for it in s.items:
            sup = "".join(f"<sup>[{n}]</sup>" for n in it.marks)
            parts.append(f"<p>{e(it.text)}{sup}</p>")
        for g in s.gaps:
            parts.append(f"<div class='gap'>[EVIDENCE REQUIRED: {e(g)}]</div>")
        for w in s.waived:
            parts.append(f"<div class='waived'>[EVIDENCE WAIVED: {e(w)}]</div>")
    parts.append("<h2>Evidence appendix</h2><table><tr><th>#</th><th>Reference</th><th>Record</th><th>Source</th></tr>")
    for a in m.appendix:
        parts.append(f"<tr><td>{a.n}</td><td>{e(a.ref)}</td><td>{e(a.label)}</td><td>{e(a.source)}</td></tr>")
    parts.append("</table>")
    if m.disclaimer:
        parts.append(f"<p class='disclaimer'>{e(m.disclaimer)}</p>")
    parts.append(f"<p class='meta'>{e(_meta_line(m))}</p></body></html>")
    return "".join(parts)


def _meta_line(m: DocModel) -> str:
    md = m.meta
    return (f"Generated {md.get('generated_at', '')} · version {md.get('version', '')} · content hash "
            f"{str(md.get('content_hash', ''))[:16]} · mode {md.get('mode', '')}")  # fmt: skip


def render_pdf(m: DocModel) -> bytes:
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as e:  # WeasyPrint needs Pango (present in the API image, not on bare Windows)
        raise RuntimeError(f"PDF rendering unavailable on this host: {type(e).__name__}") from e
    return HTML(string=render_html(m)).write_pdf()


# ----------------------------------------------------------------------------- DOCX
def render_docx(m: DocModel) -> bytes:
    from docx import Document
    from docx.enum.text import WD_COLOR_INDEX
    from docx.shared import Pt, RGBColor

    doc = Document()
    doc.add_heading(m.title, level=0)
    if m.subtitle:
        p = doc.add_paragraph(m.subtitle)
        p.runs[0].font.color.rgb = RGBColor(0x6B, 0x72, 0x80)
    for s in m.sections:
        doc.add_heading(s.title, level=1)
        for it in s.items:
            para = doc.add_paragraph(it.text)
            if it.marks:
                r = para.add_run(" " + "".join(f"[{n}]" for n in it.marks))
                r.font.superscript = True
                r.font.color.rgb = RGBColor(0x1D, 0x4E, 0xD8)
        for g in s.gaps:
            r = doc.add_paragraph().add_run(f"[EVIDENCE REQUIRED: {g}]")
            r.bold = True
            r.font.highlight_color = WD_COLOR_INDEX.YELLOW
        for w in s.waived:
            r = doc.add_paragraph().add_run(f"[EVIDENCE WAIVED: {w}]")
            r.italic = True
            r.font.highlight_color = WD_COLOR_INDEX.GRAY_25
    doc.add_heading("Evidence appendix", level=1)
    t = doc.add_table(rows=1, cols=4)
    t.style = "Light Grid Accent 1"
    for i, h in enumerate(("#", "Reference", "Record", "Source")):
        t.rows[0].cells[i].text = h
    for a in m.appendix:
        cells = t.add_row().cells
        cells[0].text, cells[1].text, cells[2].text, cells[3].text = str(a.n), a.ref, a.label, a.source
    if m.disclaimer:
        dp = doc.add_paragraph(m.disclaimer)
        dp.runs[0].font.size = Pt(8)
    mp = doc.add_paragraph(_meta_line(m))
    mp.runs[0].font.size = Pt(7)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ----------------------------------------------------------------------------- PPTX
def render_pptx(m: DocModel) -> bytes:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    s0 = prs.slides.add_slide(prs.slide_layouts[0])
    s0.shapes.title.text = m.title
    s0.placeholders[1].text = m.subtitle

    def bullets(title: str, lines: list[tuple[str, str]]) -> None:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = title
        body = slide.placeholders[1]
        body.left, body.top, body.width, body.height = Inches(0.6), Inches(1.4), Inches(12.1), Inches(5.6)
        tf = body.text_frame
        tf.clear()
        for i, (txt, kind) in enumerate(lines):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            para.text = txt
            para.font.size = Pt(15 if kind == "claim" else 13)
            if kind == "gap":
                para.font.bold = True
                para.font.color.rgb = RGBColor(0xB4, 0x53, 0x09)
            elif kind == "waived":
                para.font.italic = True
                para.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)

    for s in m.sections:
        lines = [(marks_text(it), "claim") for it in s.items]
        lines += [(f"[EVIDENCE REQUIRED: {g}]", "gap") for g in s.gaps]
        lines += [(f"[EVIDENCE WAIVED: {w}]", "waived") for w in s.waived]
        for i in range(0, max(1, len(lines)), 7):  # at most 7 lines a slide
            bullets(s.title if i == 0 else f"{s.title} (cont.)", lines[i : i + 7] or [("No content.", "gap")])
    rows = [(f"[{a.n}] {a.label} ({a.ref}){' · ' + a.source if a.source else ''}", "ref") for a in m.appendix]
    for i in range(0, len(rows), 10):
        bullets("Evidence appendix" + (" (cont.)" if i else ""), rows[i : i + 10])
    if m.disclaimer:
        bullets("Important information", [(m.disclaimer, "ref"), (_meta_line(m), "ref")])
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# ----------------------------------------------------------------------------- XLSX helpers
def _sheet_evidence(wb: Any, m: DocModel | None, extra: list[tuple[str, str, str]] | None = None) -> None:
    ws = wb.create_sheet("Evidence")
    ws.append(["#", "Reference", "Record", "Source"])
    for a in m.appendix if m else []:
        ws.append([a.n, a.ref, a.label, a.source])
    for r in extra or []:
        ws.append(["", *r])
    ws.column_dimensions["B"].width, ws.column_dimensions["C"].width, ws.column_dimensions["D"].width = 48, 48, 40


def _gap_cell(ws: Any, cell: str, text_: str) -> None:
    from openpyxl.styles import Font, PatternFill

    ws[cell] = f"[EVIDENCE REQUIRED: {text_}]"
    ws[cell].fill = PatternFill("solid", fgColor=YELLOW)
    ws[cell].font = Font(bold=True)


def financial_model_xlsx(
    snapshots: list[dict[str, Any]],
    *,
    currency: str | None,
    horizon: int,
    trailing_months: int,
    min_cash_buffer: float,
    raise_amount: float | None,
    raise_month_offset: int | None,
    raise_probability: float | None,
    sources: list[tuple[str, str, str]],
    title: str,
) -> bytes:
    """Inputs (sourced values) → Assumptions (formulas over inputs) → Projection (formulas) → Runway (formulas).
    Only sourced inputs are typed values; every derived cell is a live Excel formula."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Inputs"
    ws.append([title])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append(["Month", "Cash", "Revenue", "Opex", "Net burn", "Source record"])
    for c in "ABCDEF":
        ws[f"{c}2"].font = Font(bold=True)
    rows = sorted(snapshots, key=lambda x: x["period"])
    for snap in rows:
        ws.append(
            [
                snap["period"],
                snap.get("cash"),
                snap.get("revenue"),
                snap.get("opex"),
                snap.get("net_burn"),
                snap.get("ref"),
            ]
        )
    first, last = 3, 2 + len(rows)
    if not rows:
        _gap_cell(ws, "A3", "monthly financial snapshots (Runway & Forecast → Import)")
        last = 3
    a = wb.create_sheet("Assumptions")
    a.append(["Assumption", "Value", "How it is derived"])
    n = max(1, min(trailing_months, len(rows) - 1)) if len(rows) > 1 else 1
    lr, fr = last, max(first, last - n)
    a.append(["Currency", currency or "", "organisation profile / snapshots"])
    a.append(["Revenue growth per month", f"=IFERROR((Inputs!C{lr}/Inputs!C{fr})^(1/{max(1, lr - fr)})-1,0)",
              f"formula: compound monthly growth over the last {max(1, lr - fr)} months of Inputs"])  # fmt: skip
    a.append(["Opex growth per month", f"=IFERROR((Inputs!D{lr}/Inputs!D{fr})^(1/{max(1, lr - fr)})-1,0)",
              f"formula: compound monthly growth over the last {max(1, lr - fr)} months of Inputs"])  # fmt: skip
    a.append(["Minimum cash buffer", min_cash_buffer, "setting MIN_CASH_BUFFER"])
    a.append(["Raise amount", raise_amount, "organisation profile raise target (input)"])
    a.append(["Raise month (1 = next month)", (raise_month_offset or 0) + 1 if raise_amount else None,
              "opportunity deadline + class decision lag (config/forecast.yaml)"])  # fmt: skip
    a.append(
        ["Probability applied to the raise", raise_probability, "stage probability (config/scoring/reference.yaml)"]
    )
    if not raise_amount:
        _gap_cell(a, "B6", "raise target in the organisation profile")
    for c in "ABC":
        a[f"{c}1"].font = Font(bold=True)
    a.column_dimensions["A"].width, a.column_dimensions["B"].width, a.column_dimensions["C"].width = 34, 18, 70
    p = wb.create_sheet("Projection")
    p.append(["Month #", "Month", "Revenue", "Opex", "Net burn", "Inflow", "Cash (end)"])
    for i in range(1, horizon + 1):
        r = i + 1
        prev_rev = f"Inputs!C{lr}" if i == 1 else f"C{r - 1}"
        prev_opex = f"Inputs!D{lr}" if i == 1 else f"D{r - 1}"
        prev_cash = f"Inputs!B{lr}" if i == 1 else f"G{r - 1}"
        p.append([
            i, f"=IFERROR(EDATE(DATEVALUE(Inputs!A{lr}&\"-01\"),{i}),\"\")",
            f"={prev_rev}*(1+Assumptions!$B$3)", f"={prev_opex}*(1+Assumptions!$B$4)", f"=D{r}-C{r}",
            f"=IF(A{r}=Assumptions!$B$7,Assumptions!$B$6*Assumptions!$B$8,0)", f"={prev_cash}-E{r}+F{r}",
        ])  # fmt: skip
        p[f"B{r}"].number_format = "yyyy-mm"
        for c in "CDEFG":
            p[f"{c}{r}"].number_format = "#,##0"
    for c in "ABCDEFG":
        p[f"{c}1"].font = Font(bold=True)
    rw = wb.create_sheet("Runway")
    end = horizon + 1
    rw.append(
        [
            "Runway (months until cash < buffer)",
            f'=IFERROR(MATCH(TRUE,INDEX(Projection!G2:G{end}<Assumptions!$B$5,0),0),"beyond {horizon} months")',
        ]
    )
    rw.append(["Zero-cash month", f'=IFERROR(TEXT(INDEX(Projection!B2:B{end},B1),"yyyy-mm"),"beyond the horizon")'])
    rw.append(["Starting cash", f"=Inputs!B{lr}"])
    rw.append(["Latest monthly net burn", f"=Inputs!E{lr}"])
    rw.column_dimensions["A"].width = 42
    _sheet_evidence(wb, None, sources)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def budget_xlsx(
    lines: list[dict[str, Any]], currency: str | None, title: str, sources: list[tuple[str, str, str]]
) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Budget"
    ws.append([title])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append(["Category", "Item", f"Amount ({currency or 'currency?'})", "Source"])
    for c in "ABCD":
        ws[f"{c}2"].font = Font(bold=True)
    for b in lines:
        ws.append([b["category"], b["item"], b["amount"], "organisation profile budget_lines"])
    last = 2 + len(lines)
    if not lines:
        _gap_cell(ws, "A3", "budget lines (category, item, amount) in the organisation profile")
        last = 3
    ws.append([])
    ws.append(["Total", "", f"=SUM(C3:C{last})", "formula"])
    cats = list(dict.fromkeys(b["category"] for b in lines))
    s = wb.create_sheet("By category")
    s.append(["Category", "Amount", "Share"])
    for i, c in enumerate(cats, start=2):
        s.append(
            [c, f"=SUMIF(Budget!A3:A{last},A{i},Budget!C3:C{last})", f"=IFERROR(B{i}/SUM($B$2:$B${len(cats) + 1}),0)"]
        )
        s[f"C{i}"].number_format = "0.0%"
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 24, 48
    _sheet_evidence(wb, None, sources)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def dd_checklist_xlsx(items: list[dict[str, Any]], title: str) -> bytes:
    """items: [{key, title, documents: [{title, version, checksum, approved}]}]; status is a live formula."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "DD checklist"
    ws.append([title])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append(["Item", "Approved documents", "Document versions / SHA-256", "Status"])
    for c in "ABCD":
        ws[f"{c}2"].font = Font(bold=True)
    for i, it in enumerate(items, start=3):
        docs = [d for d in it["documents"] if d.get("approved")]
        ws.append([it["title"], len(docs), "; ".join(f"{d['title']} v{d['version']} {d['checksum'][:12]}" for d in docs),
                   f'=IF(B{i}>0,"Covered","[EVIDENCE REQUIRED]")'])  # fmt: skip
    n = 2 + len(items)
    ws.append([])
    ws.append(["Covered", f'=COUNTIF(D3:D{n},"Covered")', f"of {len(items)}"])
    ws.column_dimensions["A"].width, ws.column_dimensions["C"].width = 60, 70
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


CONTENT_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


def today() -> str:
    return date.today().isoformat()
