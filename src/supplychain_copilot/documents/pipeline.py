"""Run extraction + chunking for all registered documents.

Outputs (gitignored):
  data/processed/document_chunks.parquet   one row per chunk (DOCUMENT_CHUNKS schema)
  data/processed/documents.parquet         one row per document (provenance)
  data/processed/document_extraction.json  per-page stats and flags

Usage:
    python -m supplychain_copilot.documents.pipeline
"""

from __future__ import annotations

import json
from dataclasses import asdict

import pandas as pd
import pymupdf

from supplychain_copilot.config import PROJECT_ROOT
from supplychain_copilot.documents.chunking import chunk_document
from supplychain_copilot.documents.extract import extract_document
from supplychain_copilot.documents.registry import DOCUMENTS, DocumentSpec
from supplychain_copilot.ingestion.download_data import load_manifest, sha256_of

PROCESSED = PROJECT_ROOT / "data" / "processed"
CHUNKS_PARQUET = PROCESSED / "document_chunks.parquet"
DOCS_PARQUET = PROCESSED / "documents.parquet"
EXTRACTION_JSON = PROCESSED / "document_extraction.json"
PARSER_VERSION = f"pymupdf-{pymupdf.__version__}/scc-docs-1"


class ProvenanceError(RuntimeError):
    pass


def _verify(spec: DocumentSpec) -> str:
    expected = load_manifest()["documents"]["files"][spec.filename]
    actual = sha256_of(spec.path)
    if actual != expected["sha256"] or expected["url"] != spec.source_url:
        raise ProvenanceError(f"{spec.filename}: hash or URL does not match data/manifest.json")
    return actual


def run() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    chunk_rows, doc_rows, extraction = [], [], {}
    for spec in DOCUMENTS:
        file_sha = _verify(spec)
        pages, excluded = extract_document(spec)
        chunks = chunk_document(spec, pages)
        with pymupdf.open(spec.path) as pdf:
            page_count = pdf.page_count
        doc_rows.append(
            {
                "document_id": spec.document_id,
                "document_title": spec.title,
                "document_type": spec.document_type,
                "publisher": spec.publisher,
                "source_url": spec.source_url,
                "document_version": spec.document_version,
                "version_evidence": spec.version_evidence,
                "publication_date": spec.publication_date,
                "publication_date_evidence": spec.publication_date_evidence,
                "access_group": spec.access_group,
                "source_file": spec.filename,
                "source_sha256": file_sha,
                "page_count": page_count,
                "pages_included": len(pages),
                "pages_excluded_json": json.dumps({str(p): r for p, r in excluded.items()}),
                "chunk_count": len(chunks),
                "parser_version": PARSER_VERSION,
            }
        )
        for c in chunks:
            row = asdict(c)
            row.update(
                document_title=spec.title,
                document_type=spec.document_type,
                source_url=spec.source_url,
                document_version=spec.document_version,
                publication_date=spec.publication_date,
                access_group=spec.access_group,
                source_sha256=file_sha,
                parser_version=PARSER_VERSION,
            )
            chunk_rows.append(row)
        extraction[spec.document_id] = {
            "excluded": {str(p): r for p, r in excluded.items()},
            "pages": [
                {
                    "pdf_page": p.pdf_page,
                    "printed_label": p.printed_label,
                    "chars": p.chars,
                    "tables_kept": p.tables_kept,
                    "tables_rejected": p.tables_rejected,
                    "formula_runs": p.formula_runs,
                    "flags": p.flags,
                    "headings": [
                        e.text
                        for e in p.elements
                        if e.kind.startswith("heading") or e.kind == "page_title"
                    ],
                }
                for p in pages
            ],
        }
    return pd.DataFrame(chunk_rows), pd.DataFrame(doc_rows), extraction


def main() -> int:
    chunks, docs, extraction = run()
    PROCESSED.mkdir(parents=True, exist_ok=True)
    chunks.to_parquet(CHUNKS_PARQUET, index=False)
    docs.to_parquet(DOCS_PARQUET, index=False)
    EXTRACTION_JSON.write_text(json.dumps(extraction, indent=2), encoding="utf-8")
    for d in docs.itertuples():
        sub = chunks[chunks.document_id == d.document_id]
        print(
            f"{d.document_id:<22} pages {d.pages_included:>3}/{d.page_count:<3} chunks {d.chunk_count:>3} "
            f"tokens min/median/max {sub.token_estimate.min()}/{int(sub.token_estimate.median())}/{sub.token_estimate.max()}"
        )
    print(f"Wrote {CHUNKS_PARQUET.relative_to(PROJECT_ROOT)} ({len(chunks)} chunks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
