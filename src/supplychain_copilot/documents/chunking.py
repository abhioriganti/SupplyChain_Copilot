"""Heading-aware chunking with provenance.

Rules:
  * Sections are delimited by detected headings (heading1 = document part / slide section / 10-K
    Item; heading2 = numbered subsection or bold sub-heading). A chunk never spans two heading1s.
  * Target ~350-600 tokens. Sections <= MAX_TOKENS become one chunk. Longer sections are split at
    paragraph boundaries (sentence boundaries if one paragraph is too long); only those splits get a
    one-sentence overlap, because a split is the only place context is lost.
  * Sections smaller than MIN_TOKENS are merged with the following section of the same heading1
    so tiny fragments (a heading plus one line) don't become low-information chunks.
  * Tables are never split. Heading text that appears in the source is kept in the chunk text.
  * Token counts are an estimate (words x 1.33); no tokenizer dependency.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field

from supplychain_copilot.documents.extract import Element, PageResult
from supplychain_copilot.documents.registry import DocumentSpec

MIN_TOKENS, TARGET_TOKENS, MAX_TOKENS = 80, 450, 600
OVERLAP_MAX_TOKENS = 60
_SENT_END = re.compile(r'[.!?:"”)\]]$')


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text.split()) * 1.33)


@dataclass
class Unit:
    text: str
    pdf_page: int
    printed_label: str | None
    is_table: bool = False
    is_heading: bool = False


@dataclass
class Section:
    heading1: str
    heading2s: list[str]
    units: list[Unit] = field(default_factory=list)

    @property
    def tokens(self) -> int:
        return sum(estimate_tokens(u.text) for u in self.units)

    @property
    def title(self) -> str:
        subs = [h for h in dict.fromkeys(self.heading2s) if h]
        return self.heading1 + (" > " + "; ".join(subs) if subs else "")


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    chunk_index: int
    section_title: str
    page_number: int
    page_end: int
    printed_page_start: str | None
    printed_page_end: str | None
    chunk_text: str
    token_estimate: int
    contains_table: bool
    content_hash: str
    overlap_prefix: bool
    extraction_flags: str


def _title_case(t: str) -> str:
    if t.isupper():
        small = {"and", "of", "the", "in", "for", "to", "or", "a", "an", "on"}
        words = t.lower().split()
        return " ".join(
            w if (i and w in small) else w[:1].upper() + w[1:] for i, w in enumerate(words)
        )
    return t


def _same_name(a: str, b: str) -> bool:
    strip = lambda s: re.sub(r"^\d+\.\s*", "", s).strip().lower()  # noqa: E731
    return strip(a) == strip(b)


def build_sections(spec: DocumentSpec, pages: list[PageResult]) -> list[Section]:
    sections: list[Section] = []
    current = Section(
        heading1=spec.title if spec.layout == "report" else "Introduction", heading2s=[]
    )

    def close() -> None:
        nonlocal current
        if current.units:
            sections.append(current)

    last_page: int | None = None
    for page in pages:
        if last_page is not None and page.pdf_page != last_page + 1:
            # Never let a section run across excluded pages: citations must stay contiguous.
            close()
            current = Section(heading1=current.heading1, heading2s=list(current.heading2s))
        last_page = page.pdf_page
        for el in page.elements:
            if el.kind in ("heading1", "page_title"):
                name = _title_case(el.text)
                if el.kind == "page_title" and _same_name(name, current.heading1):
                    continue  # running slide header repeating the current section
                close()
                current = Section(heading1=name, heading2s=[])
                current.units.append(Unit(el.text, el.pdf_page, el.printed_label, is_heading=True))
            elif el.kind == "heading2":
                close()
                current = Section(heading1=current.heading1, heading2s=[el.text])
                current.units.append(Unit(el.text, el.pdf_page, el.printed_label, is_heading=True))
            else:
                _append(current, el)
    close()
    return _merge_small(sections)


def _append(section: Section, el: Element) -> None:
    is_table = el.kind == "table"
    prev = section.units[-1] if section.units else None
    # Re-join line fragments split into separate blocks (e.g. magazine-style pages).
    if (
        prev
        and not prev.is_table
        and not prev.is_heading
        and not is_table
        and prev.pdf_page == el.pdf_page
        and not _SENT_END.search(prev.text)
        and not el.text.startswith("• ")
        and len(prev.text) < 2000
    ):
        prev.text = f"{prev.text} {el.text}"
        return
    section.units.append(Unit(el.text, el.pdf_page, el.printed_label, is_table))


def _heading_only(s: Section) -> bool:
    return len(s.units) == 1 and s.tokens <= 20


def _merge_small(sections: list[Section]) -> list[Section]:
    merged: list[Section] = []
    for s in sections:
        if merged and _heading_only(merged[-1]) and merged[-1].heading1 != s.heading1:
            merged.pop()  # a heading with no body (divider slide, image-only page) carries no evidence
        if merged and _heading_only(merged[-1]) and merged[-1].heading1 == s.heading1:
            # A heading with no body of its own always travels with the section that follows it.
            merged[-1].units += s.units
            merged[-1].heading2s += s.heading2s
            continue
        if (
            merged
            and merged[-1].heading1 == s.heading1
            and (merged[-1].tokens < MIN_TOKENS or s.tokens < MIN_TOKENS)
            and merged[-1].tokens + s.tokens <= MAX_TOKENS
        ):
            merged[-1].units += s.units
            merged[-1].heading2s += s.heading2s
        else:
            merged.append(s)
    if merged and _heading_only(merged[-1]):
        merged.pop()
    return merged


def _split_long(unit: Unit) -> list[Unit]:
    if estimate_tokens(unit.text) <= MAX_TOKENS:
        return [unit]
    if unit.is_table:  # split by rows, repeating the table marker so each piece is self-describing
        marker, *rows = unit.text.splitlines()
        pieces, buf = [], []
        for row in rows:
            if buf and estimate_tokens("\n".join([marker, *buf, row])) > TARGET_TOKENS:
                pieces.append(
                    Unit(
                        "\n".join([f"{marker} (continued)" if pieces else marker, *buf]),
                        unit.pdf_page,
                        unit.printed_label,
                        True,
                    )
                )
                buf = []
            buf.append(row)
        if buf:
            pieces.append(
                Unit(
                    "\n".join([f"{marker} (continued)" if pieces else marker, *buf]),
                    unit.pdf_page,
                    unit.printed_label,
                    True,
                )
            )
        return pieces
    parts, buf = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", unit.text):
        if buf and estimate_tokens(buf + " " + sent) > TARGET_TOKENS:
            parts.append(Unit(buf, unit.pdf_page, unit.printed_label))
            buf = sent
        else:
            buf = f"{buf} {sent}".strip()
    if buf:
        parts.append(Unit(buf, unit.pdf_page, unit.printed_label))
    return parts


def _last_sentence(text: str) -> str | None:
    sents = re.split(r"(?<=[.!?])\s+", text.strip())
    last = sents[-1] if sents else ""
    return (
        last
        if last and estimate_tokens(last) <= OVERLAP_MAX_TOKENS and not last.startswith("[Table")
        else None
    )


def section_to_groups(section: Section) -> list[tuple[list[Unit], bool]]:
    """Return lists of units per chunk and whether the chunk starts with an overlap sentence."""
    if section.tokens <= MAX_TOKENS:
        return [(section.units, False)]
    units = [u for raw in section.units for u in _split_long(raw)]
    groups: list[tuple[list[Unit], bool]] = []
    buf: list[Unit] = []
    overlap = False
    for u in units:
        size = sum(estimate_tokens(x.text) for x in buf)
        if buf and size + estimate_tokens(u.text) > TARGET_TOKENS and size >= MIN_TOKENS:
            groups.append((buf, overlap))
            carry = _last_sentence(buf[-1].text) if not buf[-1].is_table else None
            buf = [Unit(carry, buf[-1].pdf_page, buf[-1].printed_label)] if carry else []
            overlap = carry is not None
        buf.append(u)
    if buf:
        groups.append((buf, overlap))
    return groups


def chunk_document(spec: DocumentSpec, pages: list[PageResult]) -> list[Chunk]:
    flags_by_page = {p.pdf_page: p.flags for p in pages}
    chunks: list[Chunk] = []
    for section in build_sections(spec, pages):
        for units, overlap in section_to_groups(section):
            text = "\n".join(u.text for u in units).strip()
            if not text:
                continue
            pages_used = [u.pdf_page for u in units]
            # A printed label is only valid for the page it was printed on: take the start label from
            # the chunk's first page and the end label from its last page (None if that page has none).
            first_label = next(
                (u.printed_label for u in units if u.pdf_page == min(pages_used)), None
            )
            last_label = next(
                (u.printed_label for u in reversed(units) if u.pdf_page == max(pages_used)), None
            )
            flags = sorted({f for p in set(pages_used) for f in flags_by_page.get(p, [])})
            identity = f"{spec.document_id}|{min(pages_used)}|{section.title}|{text}"
            chunks.append(
                Chunk(
                    chunk_id=f"{spec.document_id}-{hashlib.sha256(identity.encode()).hexdigest()[:12]}",
                    document_id=spec.document_id,
                    chunk_index=len(chunks),
                    section_title=section.title,
                    page_number=min(pages_used),
                    page_end=max(pages_used),
                    printed_page_start=first_label,
                    printed_page_end=last_label,
                    chunk_text=text,
                    token_estimate=estimate_tokens(text),
                    contains_table=any(u.is_table for u in units),
                    content_hash=hashlib.sha256(text.encode()).hexdigest(),
                    overlap_prefix=overlap,
                    extraction_flags=",".join(flags),
                )
            )
    return chunks
