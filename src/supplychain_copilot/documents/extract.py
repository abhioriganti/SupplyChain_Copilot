"""PDF extraction with PyMuPDF: ordered text blocks, real tables, headings, page labels.

Design (from manual inspection of the three PDFs):
  * Two-column slide layouts: PyMuPDF block order can put the right column first, so blocks are
    re-ordered column-aware (full-width blocks split the page into bands; left then right per band).
  * Tables: find_tables() also reports a full-page "table" on every slide; tables covering most of the
    page or with mostly empty cells are rejected. Real tables are serialized row by row and the
    overlapping text blocks are removed so values stay attached to their headers.
  * Running boilerplate (text repeated on >50% of included pages) and bare page numbers are removed;
    footer page numbers are kept as the printed page label.
  * Formula glyphs (Unicode math alphanumerics) cannot be read reliably and are replaced by an explicit
    marker instead of garbage text.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

import pymupdf

from supplychain_copilot.documents.registry import DocumentSpec

ITEM_HEADING = re.compile(r"^(?:Item\s+\d+[A-C]?\.\s*[—–-]\s*.+|PART\s+[IVX]+)$")
NUMBERED_SUBSECTION = re.compile(r"^\d+\.[1-9]\d?\s+[A-Z]")
DIVIDER = re.compile(r"^\d+\.\s*[A-Za-z][A-Za-z &()/,-]+$")
LETTER_SPACED = re.compile(r"^(?:\S ){3,}\S$")
PAGE_NUMBER = re.compile(r"^(?:\d{1,3}|[ivxlc]{1,6})$")
MATH_RUN = re.compile(r"[\U0001D400-\U0001D7FF][\U0001D400-\U0001D7FF\s\-−+*/=∗·0-9().,]*")
FORMULA_MARKER = "[formula not extracted - see source page]"


@dataclass
class Line:
    text: str
    size: float
    bold: bool
    bbox: tuple[float, float, float, float]


@dataclass
class Block:
    lines: list[Line]
    bbox: tuple[float, float, float, float]
    is_table: bool = False

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


@dataclass
class Element:
    """A unit of document text in reading order."""

    kind: str  # "heading1" | "heading2" | "text" | "table"
    text: str
    pdf_page: int
    printed_label: str | None


@dataclass
class PageResult:
    pdf_page: int
    printed_label: str | None
    elements: list[Element]
    tables_kept: int = 0
    tables_rejected: int = 0
    formula_runs: int = 0
    chars: int = 0
    flags: list[str] = field(default_factory=list)


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip().lower()


def _is_bold(span: dict) -> bool:
    return "Bold" in span["font"] or bool(span["flags"] & 16)


def _despace(line: dict) -> str:
    """Rebuild letter-spaced display text ('R E V I S I O N  R E C O R D') from character positions:
    a gap well above the typical letter gap is a real word break."""
    chars = [c for s in line["spans"] for c in s["chars"] if c["c"].strip()]
    if len(chars) < 3:
        return "".join(c["c"] for c in chars)
    gaps = [b["bbox"][0] - a["bbox"][2] for a, b in zip(chars, chars[1:], strict=False)]
    typical = sorted(gaps)[len(gaps) // 2]
    out = chars[0]["c"]
    for gap, ch in zip(gaps, chars[1:], strict=False):
        out += (" " if gap > max(2.0 * typical, typical + 4) else "") + ch["c"]
    return out


def _page_lines(page: pymupdf.Page) -> list[list[Line]]:
    """Text blocks -> lines with font info (skips image blocks)."""
    blocks: list[list[Line]] = []
    for b in page.get_text("rawdict")["blocks"]:
        lines = []
        for ln in b.get("lines", []):
            for s in ln["spans"]:
                s["text"] = "".join(c["c"] for c in s["chars"])
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in ln["spans"]).strip()
            if LETTER_SPACED.match(text):
                text = _despace(ln)
            if not MATH_RUN.search(text):  # never NFKC math glyphs: they'd become plausible letters
                text = unicodedata.normalize("NFKC", text)  # 'ﬁscal' -> 'fiscal'
            size = max(s["size"] for s in spans)
            lines.append(
                Line(text, round(size, 1), all(_is_bold(s) for s in spans), tuple(ln["bbox"]))
            )
        if lines:
            blocks.append(lines)
    return blocks


_NUMERIC = re.compile(r"[\d$.,%()\- ]+")


def _is_numeric_row(row: list[str]) -> bool:
    vals = [c for c in row if c]
    return bool(vals) and sum(bool(_NUMERIC.fullmatch(c)) for c in vals) > len(vals) / 2


def _serialize_table(rows: list[list[str | None]]) -> str | None:
    """Row-wise 'header: value' serialization so each value keeps its column meaning.

    * Up to two leading non-numeric rows form the header; a merged (sparse) first header row is
      forward-filled and combined with the second ("Quality - Quality PPM").
    * Rows with only the first cell filled (e.g. footnotes) are emitted as plain notes, not as values.
    * Tables whose header can't be identified fall back to ' | '-joined rows.
    """
    clean = [[re.sub(r"\s+", " ", c or "").strip() for c in r] for r in rows]
    clean = [r for r in clean if any(r)]
    if len(clean) < 2:
        return None
    n_header = 0
    for r in clean[:2]:
        if _is_numeric_row(r):
            break
        n_header += 1
    if n_header == 2 and len(clean) > 2 and sum(bool(c) for c in clean[0]) < len(clean[0]):
        top, last = [], ""
        for c in clean[0]:
            last = c or last
            top.append(last)
        header = [
            f"{t} - {b}" if t and b and t != b else (b or t)
            for t, b in zip(top, clean[1], strict=False)
        ]
    else:
        n_header = min(n_header, 1)
        header = clean[0] if n_header else []
    body = clean[n_header:]
    out = ["[Table]"]
    named = [h for h in header if h]
    if len(named) != len(set(named)):  # nested/ambiguous headers: don't guess the mapping
        out[0] = "[Table - layout not reliably parsed; verify against source page]"
        out += [" | ".join(c for c in r if c) for r in clean]
        return "\n".join(out)
    if header and sum(bool(h) for h in header) >= 2:
        for r in body:
            filled = [i for i, v in enumerate(r) if v]
            if filled == [0] and len(r) > 1:
                out.append(f"Note: {r[0]}")
                continue
            pairs = [f"{h}: {v}" if h else v for h, v in zip(header, r, strict=False) if v]
            if pairs:
                out.append("; ".join(pairs))
    else:
        out += [" | ".join(c for c in r if c) for r in clean]
    return "\n".join(out) if len(out) > 1 else None


def _tables(page: pymupdf.Page) -> tuple[list[tuple[tuple, str]], int]:
    """Return accepted (bbox, serialized_text) and count of rejected detections."""
    area = page.rect.width * page.rect.height
    kept, rejected = [], 0
    for t in page.find_tables().tables:
        x0, y0, x1, y1 = t.bbox
        rows = t.extract()
        cells = [c for r in rows for c in r]
        filled = sum(1 for c in cells if c and c.strip())
        if (
            (x1 - x0) * (y1 - y0) > 0.6 * area
            or t.col_count < 2
            or not cells
            or filled / len(cells) < 0.4
        ):
            rejected += 1
            continue
        text = _serialize_table(rows)
        body_rows = text.splitlines()[1:] if text else []
        if text and sum(r.startswith("Note: ") for r in body_rows) <= len(body_rows) / 2:
            kept.append(((x0, y0, x1, y1), text))
        else:  # empty, or mostly single-cell rows = flowing prose mis-detected as a table
            rejected += 1
    return kept, rejected


def _inside(bbox, outer, pad: float = 2.0) -> bool:
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return outer[0] - pad <= cx <= outer[2] + pad and outer[1] - pad <= cy <= outer[3] + pad


def _is_multi_column(blocks: list[Block], width: float) -> bool:
    """True when several column-width text blocks sit wholly in each half of the page."""
    mid = width / 2
    colw = lambda b: 0.2 * width <= b.bbox[2] - b.bbox[0] <= 0.5 * width  # noqa: E731
    left = sum(1 for b in blocks if not b.is_table and colw(b) and b.bbox[2] <= mid + 0.03 * width)
    right = sum(1 for b in blocks if not b.is_table and colw(b) and b.bbox[0] >= mid - 0.03 * width)
    return left >= 2 and right >= 2


def _reading_order(blocks: list[Block], width: float) -> list[Block]:
    """Multi-column pages: full-width blocks split the page into bands; inside a band read the left
    column (by block centre) top-down, then the right. Single-column pages: top-down, left-right."""
    if not _is_multi_column(blocks, width):
        return sorted(blocks, key=lambda b: (round(b.bbox[1]), b.bbox[0]))
    mid = width / 2
    full = lambda b: b.bbox[0] < mid - 0.05 * width and b.bbox[2] > mid + 0.05 * width  # noqa: E731
    right = lambda b: (b.bbox[0] + b.bbox[2]) / 2 >= mid  # noqa: E731
    ordered: list[Block] = []
    band: list[Block] = []
    for b in sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0])):
        if full(b):
            ordered += sorted(band, key=lambda x: (right(x), x.bbox[1]))
            band = []
            ordered.append(b)
        else:
            band.append(b)
    ordered += sorted(band, key=lambda x: (right(x), x.bbox[1]))
    return ordered


def clean_text(text: str) -> tuple[str, int]:
    """Fix extraction artifacts without inventing content. Returns (text, formula_runs_replaced)."""
    text = text.replace("\x0b", " ").replace(" ", " ")
    text, n_formula = MATH_RUN.subn(FORMULA_MARKER + " ", text)
    text = re.sub(r"(?m)^\s*[•▪●◦]\s*\n\s*", "• ", text)  # bullet glyph alone on its line
    text = re.sub(r"(\w)-\n(\w)", r"\1-\2", text)  # line-end hyphen: keep hyphen, drop break
    text = re.sub(r"(?<![.:;!?•\n])\n(?!• |\[Table\])", " ", text)  # re-flow wrapped lines
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip(), n_formula


def boilerplate_lines(doc: pymupdf.Document, pages: list[int]) -> set[str]:
    """Normalized line texts appearing on more than half of the included pages."""
    counts: Counter[str] = Counter()
    for p in pages:
        seen = {_norm(line.text) for blk in _page_lines(doc[p - 1]) for line in blk}
        counts.update(seen)
    threshold = max(2, len(pages) // 2 + 1)
    return {t for t, c in counts.items() if c >= threshold and not PAGE_NUMBER.match(t)}


def body_font_size(doc: pymupdf.Document, pages: list[int]) -> float:
    sizes: Counter[float] = Counter()
    for p in pages:
        for blk in _page_lines(doc[p - 1]):
            for line in blk:
                sizes[line.size] += len(line.text)
    return sizes.most_common(1)[0][0]


def _flush_paragraph(para: list[str], result: PageResult) -> None:
    """Emit buffered body lines as one cleaned text element, then empty the buffer."""
    if para:
        txt, n_formula = clean_text("\n".join(para))
        result.formula_runs += n_formula
        if txt:
            result.elements.append(Element("text", txt, result.pdf_page, result.printed_label))
        para.clear()


def _overlap_ratio(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])) or 1.0
    return ix * iy / smaller


def _drop_overlay_duplicates(blocks: list[Block]) -> list[Block]:
    """Some PDFs draw the same text twice at (almost) the same position (shadow/emboss effects).
    Keep one copy when two blocks have identical text and overlap heavily."""
    kept: list[Block] = []
    for b in blocks:
        if any(
            _norm(b.text) == _norm(k.text) and _overlap_ratio(b.bbox, k.bbox) > 0.5 for k in kept
        ):
            continue
        kept.append(b)
    return kept


def _title_kind(b: Block, body: float, page_height: float) -> str | None:
    """Slides: 'heading1' for section-divider titles (very large text or 'N. Title'), 'page_title'
    for the large title at the top of a content slide, else None. Based on size and position."""
    if b.is_table or len(b.lines) > 3:
        return None
    joined = re.sub(r"\s+", " ", " ".join(ln.text for ln in b.lines)).strip()
    if len(joined) > 90 or not re.search(r"[A-Za-z]{3}", joined):
        return None
    size = min(ln.size for ln in b.lines)
    if size >= 2.5 * body or (size >= 1.6 * body and DIVIDER.match(joined)):
        return "heading1"
    if size >= 1.6 * body and b.bbox[1] < 0.25 * page_height:
        return "page_title"
    return None


def extract_page(
    doc: pymupdf.Document, pdf_page: int, spec: DocumentSpec, boilerplate: set[str], body: float
) -> PageResult:
    page = doc[pdf_page - 1]
    w, h = page.rect.width, page.rect.height
    tables, rejected = _tables(page)
    printed_label: str | None = None
    blocks: list[Block] = []
    for raw in _page_lines(page):
        kept_lines = []
        for line in raw:
            n = _norm(line.text)
            if n in boilerplate:
                continue
            if PAGE_NUMBER.match(n) and (
                line.bbox[1] > 0.88 * h or line.bbox[0] > 0.9 * w or spec.layout == "slides"
            ):
                if spec.layout == "report" or n == str(pdf_page):
                    printed_label = printed_label or n
                    continue
            if any(_inside(line.bbox, tb) for tb, _ in tables):
                continue
            kept_lines.append(line)
        if kept_lines:
            xs = [ln.bbox for ln in kept_lines]
            blocks.append(
                Block(
                    kept_lines,
                    (
                        min(b[0] for b in xs),
                        min(b[1] for b in xs),
                        max(b[2] for b in xs),
                        max(b[3] for b in xs),
                    ),
                )
            )
    blocks = _drop_overlay_duplicates(blocks)
    for tb, ttext in tables:
        blocks.append(Block([Line(ttext, body, False, tb)], tb, is_table=True))
    if spec.layout == "slides" and printed_label is None and pdf_page > 1:
        printed_label = None  # slides without a visible number keep None

    result = PageResult(
        pdf_page,
        printed_label if spec.layout == "report" else str(pdf_page) if printed_label else None,
        [],
        tables_kept=len(tables),
        tables_rejected=rejected,
    )
    ordered = _reading_order(blocks, w)
    prose_x0 = [
        ln.bbox[0] for b in ordered if not b.is_table for ln in b.lines if len(ln.text) > 40
    ]
    left_margin = min(prose_x0) if prose_x0 else 0.0

    for b in ordered:
        if b.is_table:
            result.elements.append(Element("table", b.text, pdf_page, result.printed_label))
            continue
        para: list[str] = []
        title_kind = _title_kind(b, body, h) if spec.layout == "slides" else None
        if title_kind:
            joined = re.sub(r"\s+", " ", " ".join(ln.text for ln in b.lines)).strip()
            result.elements.append(Element(title_kind, joined, pdf_page, result.printed_label))
            continue

        for line in b.lines:
            t = line.text.strip()
            kind = None
            if spec.layout == "report":
                if ITEM_HEADING.match(t) and line.bold:
                    kind = "heading1"
                elif (
                    line.bold
                    and len(t) <= 90
                    and not t.endswith((".", ",", ";"))
                    and re.search(r"[A-Za-z]{3}", t)
                    and abs(line.size - body) <= 0.6
                    and not re.search(r"\$|\d{3,}", t)
                    and t[0].isupper()
                    and line.bbox[0] <= left_margin + 6
                    and len(b.lines) <= 2
                ):
                    kind = "heading2"  # bold, body-size, at the left text margin, standalone
            elif (
                NUMBERED_SUBSECTION.match(t) and len(t.split()) <= 8 and not t.endswith(("-", ","))
            ):
                kind = (
                    "heading2"  # e.g. '7.2 Corrective Action Responses' (not numbered how-to steps)
                )
            if kind:
                _flush_paragraph(para, result)
                result.elements.append(
                    Element(kind, re.sub(r"\s+", " ", t), pdf_page, result.printed_label)
                )
            else:
                para.append(t)
        _flush_paragraph(para, result)
    result.chars = sum(len(e.text) for e in result.elements)
    if result.formula_runs:
        result.flags.append("formula_replaced")
    if any(e.kind == "table" and "not reliably parsed" in e.text for e in result.elements):
        result.flags.append("table_low_confidence")
    body_chars = sum(len(e.text) for e in result.elements if e.kind in ("text", "table"))
    if body_chars < 60:
        if any(e.kind == "heading1" for e in result.elements):
            result.flags.append("section_divider")
        elif page.get_images():
            result.flags.append("image_only_content_not_extracted")
    return result


def extract_document(spec: DocumentSpec) -> tuple[list[PageResult], dict[int, str]]:
    """Extract all included pages. Returns (page results, {excluded pdf page: reason})."""
    doc = pymupdf.open(spec.path)
    excluded = {p: r for p in range(1, doc.page_count + 1) if (r := spec.exclusion_reason(p))}
    pages = [p for p in range(1, doc.page_count + 1) if p not in excluded]
    boiler = boilerplate_lines(doc, pages)
    body = body_font_size(doc, pages)
    return [extract_page(doc, p, spec, boiler, body) for p in pages], excluded
