"""S2.4.1: done when a version is promoted only if the permission suite, retrieval
thresholds and orphaned-label check all pass (and widening is confirmed).

The real corpus in chatbot_test with the fake embedder and a rank-keeping reranker; a
small golden subset, three entitlement sets and golden-only permission queries keep each
gate run under a second.
Broken behaviour (a leak, a regression) is injected by wrapping the real retriever.
"""

import dataclasses
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

import psycopg
import pytest
from pgvector.psycopg import register_vector_async
from psycopg_pool import AsyncConnectionPool

from chatbot.evals.permissions import Entitlement, Query
from chatbot.ingest.anchors import headings_of
from chatbot.ingest.build import PromotionError, build_index, list_versions, promote, record_gate
from chatbot.ingest.chunker import Chunker
from chatbot.ingest.gate import GateConfig, GateReport, RegressionConfig, run_gate
from chatbot.ingest.validate import ValidDoc
from chatbot.ports.retriever import Candidate
from chatbot.retrieval.hybrid import PgHybridRetriever
from chatbot.retrieval.rerank import CrossEncoderReranker
from tests.evals.test_permissions_db import PERSONAS
from tests.ingest.test_build import CATALOGUE, CORPUS, FakeEmbedder
from tests.retrieval.test_rerank import CONFIG as RERANK_CONFIG

pytestmark = pytest.mark.db

from chatbot.evals.retrieval import load_golden  # noqa: E402
from tests.evals.test_permissions_db import ROOT  # noqa: E402

GOLDEN = load_golden([ROOT / "evals" / "golden" / "synthetic_v1.yaml"])[:12]
ENTITLEMENTS = [
    Entitlement("sales_rep@globex", PERSONAS["sales_rep@globex"]),
    Entitlement("nothing", frozenset()),
    Entitlement("all", frozenset(CATALOGUE.modules)),
]
CONFIG = GateConfig(
    regression=RegressionConfig(metrics=["complete@5", "recall@5", "mrr"], tolerance=0.02)
)
RERANKER = CrossEncoderReranker(RERANK_CONFIG, score_pairs=lambda pairs: [0.0] * len(pairs))
# These tests check the gate's wiring, so the permission suite runs on the golden subset
# only. Its full coverage (every chunk's self-retrieval query) is test_permissions_db's,
# and `make ingest` always runs the full set.
PERMISSION_QUERIES = [Query(q.id, q.question) for q in GOLDEN]


@pytest.fixture
def conn(pg_url: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(pg_url, autocommit=True) as c:
        c.execute(
            "TRUNCATE chunks, embedding_cache, index_promotions, active_index, index_versions, "
            "module_catalogue RESTART IDENTITY CASCADE"
        )
        yield c


@pytest.fixture
async def pool(pg_url: str) -> AsyncIterator[AsyncConnectionPool]:
    async with AsyncConnectionPool(
        pg_url, configure=register_vector_async, min_size=1, max_size=4
    ) as p:
        yield p


class Leaky:
    """Post-filtering bug: appends a reports chunk whatever the caller may see."""

    def __init__(self, inner: PgHybridRetriever, leak: Candidate) -> None:
        self.inner, self.leak = inner, leak

    async def live_version(self) -> int:
        return await self.inner.live_version()

    async def search(
        self, query: str, allowed_modules: frozenset[str], k: int, *, index_version: int
    ) -> list[Candidate]:
        return [
            *await self.inner.search(query, allowed_modules, k, index_version=index_version),
            self.leak,
        ]


class Degraded:
    """A worse retriever, but only on the new version: reverses each ranking."""

    def __init__(self, inner: PgHybridRetriever, version: int) -> None:
        self.inner, self.version = inner, version

    async def live_version(self) -> int:
        return await self.inner.live_version()

    async def search(
        self, query: str, allowed_modules: frozenset[str], k: int, *, index_version: int
    ) -> list[Candidate]:
        got = await self.inner.search(query, allowed_modules, k, index_version=index_version)
        return got[::-1] if index_version == self.version else got


def live(conn: psycopg.Connection[Any]) -> int | None:
    return next((v.index_version for v in list_versions(conn) if "live" in v.aliases), None)


def build(conn: psycopg.Connection[Any], docs: Sequence[ValidDoc] = CORPUS) -> int:
    embedder = FakeEmbedder()
    chunker = Chunker(embedder.count_tokens, tokenizer_name=embedder.key)
    return build_index(
        conn, docs, chunker=chunker, embedder=embedder, catalogue=CATALOGUE
    ).index_version


async def gate_and_promote(
    conn: psycopg.Connection[Any],
    pool: AsyncConnectionPool,
    docs: Sequence[ValidDoc] = CORPUS,
    *,
    wrap: Any = None,
    confirm: bool = False,
) -> GateReport:
    """What `make ingest` does: build, gate, record, promote only on a pass."""
    version, current = build(conn, docs), live(conn)
    retriever: Any = PgHybridRetriever(pool, FakeEmbedder())
    if wrap is not None:
        retriever = wrap(retriever, version)
    report = await run_gate(
        pool,
        version,
        current,
        retriever=retriever,
        reranker=RERANKER,
        golden=GOLDEN,
        personas=PERSONAS,
        entitlements=ENTITLEMENTS,
        threshold=0.3,
        config=CONFIG,
        confirm_widening=confirm,
        permission_queries=PERMISSION_QUERIES,
    )
    record_gate(conn, version, report.to_json())
    if report.passed:
        promote(conn, version)
    return report


def status(conn: psycopg.Connection[Any], version: int) -> str:
    return next(v.status for v in list_versions(conn) if v.index_version == version)


# --- a clean build passes -------------------------------------------------------------------


async def test_the_first_version_passes_and_goes_live(
    conn: psycopg.Connection[Any], pool: AsyncConnectionPool
) -> None:
    report = await gate_and_promote(conn, pool)
    assert report.passed, report.failures
    assert report.regression["note"] == "no live version to compare with"
    assert report.permissions["checked"] > 0 and report.permissions["violations"] == []
    assert live(conn) == report.version


async def test_an_identical_rebuild_passes_against_the_live_version(
    conn: psycopg.Connection[Any], pool: AsyncConnectionPool
) -> None:
    first = await gate_and_promote(conn, pool)
    second = await gate_and_promote(conn, pool)
    assert second.passed, second.failures
    assert second.live_version == first.version
    assert (
        second.regression["regressions"] == []
        and second.regression["new"] == second.regression["live"]
    )
    assert second.widening["widened"] == []
    stored = conn.execute(
        "SELECT gate_report->>'passed', gated_at IS NOT NULL FROM index_versions "
        "WHERE index_version = %s",
        (second.version,),
    ).fetchone()
    assert stored == ("true", True)
    assert live(conn) == second.version


# --- each check blocks promotion ------------------------------------------------------------


async def test_a_renamed_heading_orphans_a_label_and_blocks(
    conn: psycopg.Connection[Any], pool: AsyncConnectionPool
) -> None:
    first = await gate_and_promote(conn, pool)
    label = GOLDEN[0].expected[next(iter(GOLDEN[0].expected))].required[0]
    doc_id, anchor = label.split("#")
    doc = next(d for d in CORPUS if d.doc_id == doc_id)
    heading = next(h for h in headings_of(doc.body) if h.anchor == anchor)
    renamed = dataclasses.replace(
        doc, body=doc.body.replace(f"## {heading.text}\n", f"## {heading.text} renamed\n")
    )
    report = await gate_and_promote(conn, pool, [renamed if d is doc else d for d in CORPUS])
    assert not report.passed and report.orphans == [label]
    assert status(conn, report.version) == "failed"
    assert live(conn) == first.version, "the live index is untouched"


async def test_a_leak_blocks_promotion(
    conn: psycopg.Connection[Any], pool: AsyncConnectionPool
) -> None:
    first = await gate_and_promote(conn, pool)
    row = conn.execute(
        "SELECT chunk_id, doc_id, anchor, content_hash FROM chunks "
        "WHERE index_version = %s AND modules = '{reports}' LIMIT 1",
        (first.version,),
    ).fetchone()
    assert row is not None, "the corpus has a reports-only chunk"
    leak = Candidate(row[0], row[1], row[2], "B", "C", row[3], ("reports",), 0, 1, None, 0.1)
    report = await gate_and_promote(conn, pool, wrap=lambda r, v: Leaky(r, leak))
    assert not report.passed
    assert any(f.startswith("permission leaks:") for f in report.failures)
    assert report.permissions["violations"][0]["chunk_id"] == leak.chunk_id
    assert live(conn) == first.version


async def test_a_recall_regression_blocks_promotion(
    conn: psycopg.Connection[Any], pool: AsyncConnectionPool
) -> None:
    first = await gate_and_promote(conn, pool)
    report = await gate_and_promote(conn, pool, wrap=Degraded)
    assert not report.passed
    assert report.regression["regressions"], "the reversed rankings must regress"
    assert any("regressed" in f for f in report.failures)
    assert live(conn) == first.version


async def test_widening_blocks_unless_confirmed(
    conn: psycopg.Connection[Any], pool: AsyncConnectionPool
) -> None:
    first = await gate_and_promote(conn, pool)
    doc = next(d for d in CORPUS if d.modules == ("deals", "reports"))
    widened = [dataclasses.replace(d, modules=("reports",)) if d is doc else d for d in CORPUS]

    blocked = await gate_and_promote(conn, pool, widened)
    assert [(w["doc_id"], tuple(w["dropped"])) for w in blocked.widening["widened"]] == [
        (doc.doc_id, ("deals",))
    ]
    assert any("widened" in f for f in blocked.failures)
    assert live(conn) == first.version

    confirmed = await gate_and_promote(conn, pool, widened, confirm=True)
    assert confirmed.widening["confirmed"] is True
    assert not any("widened" in f for f in confirmed.failures)


async def test_a_failed_version_can_never_be_promoted_but_rollback_still_works(
    conn: psycopg.Connection[Any], pool: AsyncConnectionPool
) -> None:
    v1 = (await gate_and_promote(conn, pool)).version
    v2 = (await gate_and_promote(conn, pool)).version
    bad = await gate_and_promote(conn, pool, wrap=Degraded)
    with pytest.raises(PromotionError, match="has not passed"):
        promote(conn, bad.version)
    from chatbot.ingest.build import rollback

    assert rollback(conn) == v1 and live(conn) == v1
    assert v2 != v1
