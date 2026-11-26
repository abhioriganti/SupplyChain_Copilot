"""Cortex Search REST client returning citation-ready passages.

Endpoint (docs.snowflake.com, query-cortex-search-service):
  POST /api/v2/databases/{db}/schemas/{schema}/cortex-search-services/{service}:query
  body: query, columns, filter, limit, scoring_config
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from supplychain_copilot.config import SnowflakeSettings, load_settings
from supplychain_copilot.snowflake.rest import SnowflakeRestClient

DATABASE, SCHEMA, SERVICE = "SCC_DB", "AI", "SUPPLIER_DOCS_SEARCH"
RETURN_COLUMNS = [
    "CHUNK_ID",
    "DOCUMENT_ID",
    "DOCUMENT_TITLE",
    "DOCUMENT_TYPE",
    "SECTION_TITLE",
    "PAGE_NUMBER",
    "PAGE_END",
    "PRINTED_PAGE_START",
    "PRINTED_PAGE_END",
    "SOURCE_URL",
    "DOCUMENT_VERSION",
    "PUBLICATION_DATE",
    "ACCESS_GROUP",
    "CHUNK_TEXT",
]

# Retrieval configurations compared in the Phase 5 evaluation (scoring_config per query).
# Observed (not documented): a weight of exactly 0 had no effect on rankings (identical results on
# all 33 eval questions), so keyword/vector emphasis uses 10 : 0.1, which demonstrably changes results.
CONFIGS: dict[str, dict[str, Any] | None] = {
    "hybrid_rerank": None,  # service default: vector + keyword + semantic reranker
    "hybrid_no_rerank": {"reranker": "none"},
    "keyword_weighted": {"reranker": "none", "weights": {"texts": 10.0, "vectors": 0.1}},
    "vector_weighted": {"reranker": "none", "weights": {"texts": 0.1, "vectors": 10.0}},
}


@dataclass
class Passage:
    rank: int
    chunk_id: str
    document_id: str
    document_title: str
    section_title: str
    page_number: int
    page_end: int
    printed_page_start: str | None
    source_url: str
    document_version: str
    text: str
    scores: dict[str, Any] = field(default_factory=dict)

    @property
    def citation(self) -> str:
        pages = f"p. {self.page_number}" + (
            f"-{self.page_end}" if self.page_end != self.page_number else ""
        )
        printed = (
            f" (printed p. {self.printed_page_start})"
            if self.printed_page_start and self.printed_page_start != str(self.page_number)
            else ""
        )
        return f"{self.document_title}, {self.section_title}, PDF {pages}{printed}"


@dataclass
class SearchResult:
    query: str
    passages: list[Passage]
    latency_ms: float
    request_id: str | None


class DocumentSearch:
    def __init__(
        self, settings: SnowflakeSettings | None = None, client: SnowflakeRestClient | None = None
    ):
        self._client = client or SnowflakeRestClient(settings or load_settings())
        self._path = (
            f"/api/v2/databases/{DATABASE}/schemas/{SCHEMA}/cortex-search-services/{SERVICE}:query"
        )

    def search(
        self,
        query: str,
        limit: int = 5,
        document_ids: list[str] | None = None,
        scoring_config: dict[str, Any] | None = None,
    ) -> SearchResult:
        body: dict[str, Any] = {"query": query, "columns": RETURN_COLUMNS, "limit": limit}
        filters = [{"@eq": {"ACCESS_GROUP": "public"}}]
        if document_ids:
            filters.append({"@or": [{"@eq": {"DOCUMENT_ID": d}} for d in document_ids]})
        body["filter"] = filters[0] if len(filters) == 1 else {"@and": filters}
        if scoring_config:
            body["scoring_config"] = scoring_config
        start = time.perf_counter()
        resp = self._client.post(self._path, body)
        latency = (time.perf_counter() - start) * 1000
        passages = [
            Passage(
                rank=i + 1,
                chunk_id=r["CHUNK_ID"],
                document_id=r["DOCUMENT_ID"],
                document_title=r["DOCUMENT_TITLE"],
                section_title=r["SECTION_TITLE"],
                page_number=int(r["PAGE_NUMBER"]),
                page_end=int(r["PAGE_END"]),
                printed_page_start=r.get("PRINTED_PAGE_START") or None,
                source_url=r["SOURCE_URL"],
                document_version=r["DOCUMENT_VERSION"],
                text=r["CHUNK_TEXT"],
                scores=r.get("@scores", {}) or {},
            )
            for i, r in enumerate(resp.get("results", []))
        ]
        return SearchResult(query, passages, latency, resp.get("request_id"))


def main() -> (
    int
):  # quick manual probe: python -m supplychain_copilot.retrieval.search_client "question"
    import sys

    q = " ".join(sys.argv[1:]) or "What are the supplier corrective-action deadlines?"
    res = DocumentSearch().search(q, limit=3)
    print(f"{q!r}  ({res.latency_ms:.0f} ms, request {res.request_id})")
    for p in res.passages:
        print(f"\n#{p.rank} {p.citation}\n   scores={p.scores}\n   {p.text[:300]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
