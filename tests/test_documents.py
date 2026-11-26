"""Phase 4 document-processing tests.

Unit tests (CI-safe) cover cleaning, table serialization, reading order and chunking rules.
Real-PDF tests (skipped if the PDFs are absent) check provenance: every chunk's text must be found
on the PDF pages it cites, key sections must be retained, and metadata must be complete.
"""

from __future__ import annotations

import os
import re

import pandas as pd
import pytest

from supplychain_copilot.documents import chunking as ch
from supplychain_copilot.documents.extract import (
    FORMULA_MARKER,
    Block,
    Element,
    Line,
    PageResult,
    _reading_order,
    _serialize_table,
    clean_text,
)
from supplychain_copilot.documents.registry import DOCUMENTS, get

# ----------------------------------------------------------------------------- cleaning


def test_bullet_glyph_joined_to_text():
    text, _ = clean_text("Criteria:\n•\nQuality Management System\n•\nFinancial stability")
    assert "• Quality Management System" in text and "• Financial stability" in text


def test_wrapped_lines_reflowed_and_hyphen_kept():
    text, _ = clean_text("The following are time frames for response to non-\nconformances:")
    assert text == "The following are time frames for response to non-conformances:"


def test_formula_glyphs_replaced_not_passed_through():
    text, n = clean_text("20 𝑝𝑝𝑝𝑝𝑝𝑝−𝑁𝑁𝑁𝑁 𝑜𝑜𝑜𝑜 score")
    assert n == 1 and FORMULA_MARKER in text and "𝑝" not in text


# ----------------------------------------------------------------------------- tables


def test_table_values_keep_their_headers_and_footnote_is_a_note():
    rows = [
        [
            "Containment\nCompleted",
            "Corrective and\nPreventative Actions\nCompleted",
            "Effectiveness Verified",
        ],
        ["2 working days", "14 working days", "30 working days"],
        ["1) On receipt of the quality complaint", "", ""],
    ]
    out = _serialize_table(rows)
    assert "Containment Completed: 2 working days" in out
    assert "Corrective and Preventative Actions Completed: 14 working days" in out
    assert "Note: 1) On receipt" in out


def test_merged_two_row_header_is_combined():
    rows = [
        ["Quality", "", "Delivery"],
        ["Quality PPM", "Quality Impact", "On-Time Delivery"],
        ["25", "15", "25"],
    ]
    out = _serialize_table(rows)
    assert "Quality - Quality PPM: 25" in out and "Quality - Quality Impact: 15" in out


def test_ambiguous_nested_header_is_flagged_not_guessed():
    rows = [
        ["PPM Range", "", "PPM Range", ""],
        ["Low", "High", "Low", "High"],
        ["0", "500", "0", "1500"],
    ]
    out = _serialize_table(rows)
    assert out.startswith("[Table - layout not reliably parsed")


# ----------------------------------------------------------------------------- reading order


def _blk(x0, y0, x1, y1, text):
    return Block([Line(text, 14, False, (x0, y0, x1, y1))], (x0, y0, x1, y1))


def test_two_column_slide_reads_left_column_first():
    w = 960
    blocks = [
        _blk(500, 120, 900, 140, "1.3 Identification"),
        _blk(40, 100, 450, 120, "1.1 Definition"),
        _blk(40, 300, 450, 320, "1.2 Responsibility"),
        _blk(500, 300, 900, 320, "more right column"),
        _blk(40, 20, 600, 60, "SAFETY MANAGEMENT"),  # full-width header
    ]
    order = [b.text for b in _reading_order(blocks, w)]
    assert order == [
        "SAFETY MANAGEMENT",
        "1.1 Definition",
        "1.2 Responsibility",
        "1.3 Identification",
        "more right column",
    ]


def test_single_column_page_keeps_top_down_order():
    blocks = [_blk(47, 300, 560, 320, "second"), _blk(47, 100, 560, 120, "first")]
    assert [b.text for b in _reading_order(blocks, 603)] == ["first", "second"]


# ----------------------------------------------------------------------------- chunking


def _page(n, elements):
    return PageResult(n, str(n), [Element(k, t, n, str(n)) for k, t in elements])


def test_chunks_respect_max_size_and_heading_boundaries():
    spec = get("WOR-SQAM-2025-10-23")
    long_para = " ".join(["Suppliers shall document every change and notify Worthington."] * 120)
    pages = [
        _page(
            10,
            [
                ("heading1", "2. SUPPLIER SELECTION"),
                ("heading2", "2.1 Supplier Evaluation"),
                ("text", long_para),
            ],
        ),
        _page(
            11,
            [
                ("heading1", "3. ADVANCED PRODUCT QUALITY PLANNING"),
                ("text", "Short body text. " * 30),
            ],
        ),
    ]
    chunks = ch.chunk_document(spec, pages)
    assert all(c.token_estimate <= ch.MAX_TOKENS + ch.OVERLAP_MAX_TOKENS for c in chunks)
    assert len({c.section_title.split(" > ")[0] for c in chunks}) == 2
    assert not any("2. Supplier" in c.section_title and c.page_number == 11 for c in chunks)
    assert any(
        c.overlap_prefix for c in chunks
    )  # overlap only appears where a long section was split


def test_chunk_ids_are_stable_and_hash_matches_text():
    import hashlib

    spec = get("WOR-SCOC-2025-06")
    pages = [
        _page(
            4,
            [
                ("page_title", "OCCUPATIONAL HEALTH AND SAFETY"),
                ("text", "Suppliers should implement a safety system. " * 20),
            ],
        )
    ]
    a, b = ch.chunk_document(spec, pages), ch.chunk_document(spec, pages)
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert all(c.content_hash == hashlib.sha256(c.chunk_text.encode()).hexdigest() for c in a)


def test_heading_only_divider_produces_no_chunk():
    spec = get("WOR-SQAM-2025-10-23")
    pages = [
        _page(35, [("heading1", "APPENDICES")]),
        _page(
            36,
            [
                ("page_title", "APPENDIX A – Supplier Portal"),
                ("text", "Log in to the portal. " * 30),
            ],
        ),
    ]
    chunks = ch.chunk_document(spec, pages)
    assert all(c.page_number != 35 for c in chunks)


def test_registry_metadata_complete():
    for d in DOCUMENTS:
        assert d.source_url.startswith("https://") and d.document_version and d.publication_date
        assert d.version_evidence and d.publication_date_evidence and d.access_group == "public"


# ----------------------------------------------------------------------------- real PDFs

have_pdfs = all(d.path.is_file() for d in DOCUMENTS)
real = pytest.mark.skipif(not have_pdfs, reason="source PDFs not present (never committed)")
REQUIRED = [
    "chunk_id",
    "document_id",
    "document_title",
    "document_type",
    "section_title",
    "page_number",
    "chunk_text",
    "source_url",
    "document_version",
    "publication_date",
    "access_group",
    "content_hash",
]


@pytest.fixture(scope="module")
def corpus():
    from supplychain_copilot.documents.pipeline import run

    chunks, docs, extraction = run()
    return chunks, docs, extraction


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


@real
def test_every_word_of_every_chunk_is_on_its_cited_pages(corpus):
    """Hard provenance check: every word in every chunk (tables included, minus the markers this
    pipeline adds) occurs on the PDF pages the chunk cites. Catches invented or mis-attributed text.
    Word *order* fidelity is measured separately in the extraction quality report."""
    from supplychain_copilot.documents.quality import chunk_word_coverage, page_words

    chunks, _, _ = corpus
    words = page_words()
    bad = []
    for r in chunks.itertuples():
        cov, missing = chunk_word_coverage(
            r.chunk_text, r.document_id, r.page_number, r.page_end, words
        )
        if missing:
            bad.append((r.chunk_id, r.page_number, sorted(missing)[:5]))
    assert bad == [], bad[:5]


@real
def test_metadata_complete_and_ids_unique(corpus):
    chunks, docs, _ = corpus
    assert chunks[REQUIRED].notna().all().all()
    assert chunks.chunk_id.is_unique
    assert set(chunks.document_id) == {d.document_id for d in DOCUMENTS} == set(docs.document_id)
    # smallest legitimate chunk: 'Item 1B. - Unresolved Staff Comments / None.' (a complete disclosure)
    assert (chunks.token_estimate <= ch.MAX_TOKENS).all() and (chunks.token_estimate >= 8).all()


@real
def test_key_sections_retained_with_correct_pages(corpus):
    chunks, _, _ = corpus

    def find(pattern: str) -> pd.DataFrame:
        return chunks[chunks.chunk_text.str.contains(pattern, regex=True)]

    ca = find("Corrective and Preventative Actions Completed: 14 working days")
    assert (
        len(ca) == 1
        and ca.iloc[0].page_number == 29
        and "7.2 Corrective Action" in ca.iloc[0].section_title
    )
    risk = chunks[chunks.section_title.str.contains("Raw Material Pricing and Availability")]
    assert (
        not risk.empty and risk.iloc[0].page_number == 28 and risk.iloc[0].printed_page_start == "8"
    )
    scoc = chunks[chunks.section_title.str.contains("Responsible Supply Chain Management")]
    assert not scoc.empty and "OECD" in scoc.iloc[0].chunk_text
    assert not find("Item 8\\. — Financial Statements").shape[0]  # excluded scope stays excluded


@real
def test_excluded_pages_never_cited(corpus):
    chunks, _, _ = corpus
    for d in DOCUMENTS:
        sub = chunks[chunks.document_id == d.document_id]
        for r in sub.itertuples():
            assert all(d.exclusion_reason(p) is None for p in range(r.page_number, r.page_end + 1))


live = pytest.mark.skipif(
    os.getenv("SCC_RUN_SNOWFLAKE_TESTS") != "1", reason="set SCC_RUN_SNOWFLAKE_TESTS=1"
)


@pytest.mark.snowflake
@live
def test_snowflake_document_chunks_match_parquet():
    from supplychain_copilot.documents.load import verify_loaded

    result = verify_loaded()
    assert result["mismatches"] == [], result
