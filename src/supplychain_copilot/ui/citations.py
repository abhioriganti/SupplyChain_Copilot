"""Turn agent citations into displayable source references with page-level PDF links."""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from supplychain_copilot.agent.client import Citation

_PAGE = re.compile(r"PDF p\. (\d+)(?:-(\d+))?")


@dataclass(frozen=True)
class SourceRef:
    chunk_id: str
    document_title: str
    section: str
    pages: str
    url: str
    version: str
    snippet: str


def clean_snippet(snippet: str, document_title: str) -> str:
    """Citation text is the search column, which starts with 'Document - Section'. Drop that line so
    the snippet shows the passage itself (the panel already shows document and section)."""
    s = (snippet or "").strip()
    if document_title and s.startswith(document_title):
        s = s.split("\n", 1)[1] if "\n" in s else s[len(document_title) :]
    return s.strip()


def pdf_page_link(url: str, page: int) -> str:
    """Most PDF viewers honour the #page=N fragment."""
    return f"{url}#page={page}" if url else ""


def build_sources(citations: list[Citation], meta: pd.DataFrame) -> list[SourceRef]:
    """Prefer authoritative chunk metadata from DOCS.DOCUMENT_CHUNKS; fall back to the citation label."""
    by_id = (
        {}
        if meta is None or meta.empty
        else {r["CHUNK_ID"]: r for r in meta.to_dict(orient="records")}
    )
    out: list[SourceRef] = []
    for c in citations:
        m = by_id.get(c.chunk_id)
        if m:
            start, end = int(m["PAGE_NUMBER"]), int(m["PAGE_END"])
            pages = f"PDF p. {start}" + (f"-{end}" if end != start else "")
            if m.get("PRINTED_PAGE_START") and str(m["PRINTED_PAGE_START"]) != str(start):
                pages += f" (printed p. {m['PRINTED_PAGE_START']})"
            out.append(
                SourceRef(
                    c.chunk_id,
                    m["DOCUMENT_TITLE"],
                    m["SECTION_TITLE"],
                    pages,
                    pdf_page_link(m["SOURCE_URL"], start),
                    m["DOCUMENT_VERSION"],
                    clean_snippet(c.snippet, m["DOCUMENT_TITLE"]),
                )
            )
            continue
        # Fallback: the agent's label is "document | section | PDF p. N[-M]" (CITATION_LABEL).
        parts = [p.strip() for p in c.label.split("|")] + ["", "", ""]
        page_match = _PAGE.search(c.label)
        pages = parts[2] or (page_match.group(0) if page_match else "")
        out.append(
            SourceRef(
                c.chunk_id,
                parts[0] or c.label,
                parts[1],
                pages,
                "",
                "",
                clean_snippet(c.snippet, parts[0]),
            )
        )
    return out
