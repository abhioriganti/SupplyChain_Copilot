"""Document registry: provenance metadata and page scope for each public PDF.

Every value here is taken from the document itself, its filename, its PDF metadata, or its URL.
The evidence for version and date is recorded next to each value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from supplychain_copilot.config import PROJECT_ROOT

DOCS_DIR = PROJECT_ROOT / "data" / "raw" / "documents"
Layout = Literal["slides", "report"]


@dataclass(frozen=True)
class PageRange:
    start: int  # 1-based PDF page, inclusive
    end: int
    reason: str


@dataclass(frozen=True)
class DocumentSpec:
    document_id: str
    title: str
    document_type: str
    filename: str
    source_url: str
    publisher: str
    document_version: str
    version_evidence: str
    publication_date: date
    publication_date_evidence: str
    layout: Layout
    access_group: str = "public"
    excluded: tuple[PageRange, ...] = field(default_factory=tuple)

    @property
    def path(self) -> Path:
        return DOCS_DIR / self.filename

    def exclusion_reason(self, pdf_page: int) -> str | None:
        for r in self.excluded:
            if r.start <= pdf_page <= r.end:
                return r.reason
        return None


DOCUMENTS: tuple[DocumentSpec, ...] = (
    DocumentSpec(
        document_id="WOR-SQAM-2025-10-23",
        title="Supplier Quality Assurance Manual",
        document_type="supplier_quality_manual",
        filename="supplier-quality-assurance-manual_102325.pdf",
        source_url="https://www.worthingtonenterprises.com/docs/default-source/default-document-library/misc.-support-docs/supplier-quality-assurance-manual_102325.pdf",
        publisher="Worthington Enterprises (public website)",
        document_version="Rev. 2025-10-23",
        version_evidence="Revision Record (PDF p.41): latest entry '10/23/25 - Updated company vision statement'",
        publication_date=date(2025, 10, 23),
        publication_date_evidence="Revision Record latest entry; filename suffix 102325; PDF creationDate 2025-10-23",
        layout="slides",
        excluded=(
            PageRange(1, 1, "cover slide (title only)"),
            PageRange(2, 2, "table of contents (navigation; headings are captured from the body)"),
        ),
    ),
    DocumentSpec(
        document_id="WOR-SCOC-2025-06",
        title="Supplier Code of Conduct",
        document_type="supplier_code_of_conduct",
        filename="supplier-code-of-conduct_06162025.pdf",
        source_url="https://www.worthingtonenterprises.com/docs/default-source/default-document-library/misc.-support-docs/supplier-code-of-conduct_06162025.pdf",
        publisher="Worthington Enterprises (public website)",
        document_version="June 2025",
        version_evidence="Cover slide text 'JUNE 2025'; filename suffix 06162025",
        publication_date=date(2025, 6, 16),
        publication_date_evidence="Filename suffix 06162025 (cover states June 2025)",
        layout="slides",
        excluded=(PageRange(1, 1, "cover slide (title and date only)"),),
    ),
    DocumentSpec(
        document_id="WOR-AR-FY2026",
        title="Worthington Enterprises 2026 Annual Report (incl. Form 10-K)",
        document_type="annual_report_10k",
        filename="2026_annual_report.pdf",
        source_url="https://www.sec.gov/Archives/edgar/data/108516/000119312526348735/2026_annual_report.pdf",
        publisher="Worthington Enterprises via SEC EDGAR (public filing)",
        document_version="Fiscal 2026 (fiscal year ended 2026-05-31)",
        version_evidence="Form 10-K cover (PDF p.9): 'fiscal year ended May 31, 2026'",
        publication_date=date(2026, 8, 7),
        publication_date_evidence="PDF creationDate 2026-08-07 (SEC accession 0001193125-26-348735)",
        layout="report",
        excluded=(
            PageRange(
                9, 20, "10-K cover, table of contents, defined terms, non-GAAP reconciliation"
            ),
            PageRange(42, 43, "Items 5-6: stock market data / reserved"),
            PageRange(
                57,
                104,
                "Item 8: financial statements and notes (numeric tables; not suited to text retrieval)",
            ),
            PageRange(
                105,
                122,
                "Items 9-16, exhibits, signatures, corporate officers (governance boilerplate)",
            ),
        ),
    ),
)


def get(document_id: str) -> DocumentSpec:
    return next(d for d in DOCUMENTS if d.document_id == document_id)
