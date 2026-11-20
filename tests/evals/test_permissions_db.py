"""S2.3.2: done when zero violations across the persona matrix and property tests; any
leak fails the build.

Runs against Postgres (`db` marker) with the fake hash embedder: the filter is SQL, so
random vectors test it fully, and identical text still gives an identical vector, so
self-retrieval works. No model download needed, so this runs in `make check` and CI.
"""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
import pytest
import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pgvector.psycopg import register_vector, register_vector_async
from psycopg_pool import AsyncConnectionPool

from chatbot.evals.permissions import (
    BOGUS_MODULES,
    Entitlement,
    Query,
    entitlement_matrix,
    run_permission_suite,
    self_retrieval_queries,
)
from chatbot.ingest.build import build_index, promote
from chatbot.ingest.chunker import Chunker
from chatbot.retrieval.hybrid import PgHybridRetriever
from chatbot.retrieval.rerank import CrossEncoderReranker
from tests.ingest.test_build import CATALOGUE, CORPUS, FakeEmbedder
from tests.retrieval.test_rerank import CONFIG as RERANK_CONFIG

pytestmark = pytest.mark.db

ROOT = Path(__file__).parents[2]
MODULES = sorted(CATALOGUE.modules)
PERSONAS = {
    p: frozenset(m)
    for p, m in yaml.safe_load((ROOT / "data" / "personas.yaml").read_text())["personas"].items()
}
GOLDEN = [
    Query(q["id"], q["question"])
    for q in yaml.safe_load((ROOT / "evals" / "golden" / "synthetic_v1.yaml").read_text())
]
# Keeps the fused order; exercises the rerank stage without a model.
RERANKER = CrossEncoderReranker(RERANK_CONFIG, score_pairs=lambda pairs: [0.0] * len(pairs))


class Env:
    """One event loop + pool for the module, so Hypothesis (sync) can drive async code."""

    def __init__(self, pg_url: str) -> None:
        self.loop = asyncio.new_event_loop()
        self.pool = AsyncConnectionPool(
            pg_url, configure=register_vector_async, min_size=1, max_size=4, open=False
        )
        self.loop.run_until_complete(self.pool.open())
        self.embedder = FakeEmbedder()
        self.retriever = PgHybridRetriever(self.pool, self.embedder)

    def run(self, coro: Any) -> Any:
        return self.loop.run_until_complete(coro)

    def close(self) -> None:
        self.loop.run_until_complete(self.pool.close())
        self.loop.close()


@pytest.fixture(scope="module")
def env(pg_url: str) -> Iterator[Env]:
    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute(
            "TRUNCATE chunks, embedding_cache, index_promotions, active_index, index_versions, "
            "module_catalogue RESTART IDENTITY CASCADE"
        )
    e = Env(pg_url)
    yield e
    e.close()


@pytest.fixture(scope="module")
def corpus(env: Env, pg_url: str) -> dict[str, Any]:
    """The real 42-doc corpus, built and promoted in chatbot_test."""
    with psycopg.connect(pg_url, autocommit=True) as conn:
        chunker = Chunker(env.embedder.count_tokens, tokenizer_name=env.embedder.key)
        r = build_index(conn, CORPUS, chunker=chunker, embedder=env.embedder, catalogue=CATALOGUE)
        promote(conn, r.index_version, ungated=True)
        rows = conn.execute(
            "SELECT chunk_id, modules, breadcrumb || E'\\n\\n' || content FROM chunks "
            "WHERE index_version = %s ORDER BY chunk_id",
            (r.index_version,),
        ).fetchall()
    return {
        "version": r.index_version,
        "modules": {cid: tuple(mods) for cid, mods, _ in rows},
        "self": self_retrieval_queries([(cid, text) for cid, _, text in rows]),
    }


# --- the persona matrix on the real corpus --------------------------------------------------


def test_the_persona_matrix_has_no_leaks_and_is_not_vacuous(
    env: Env, corpus: dict[str, Any]
) -> None:
    """Every entitlement set x every chunk queried by its own text: the strongest decoy
    real data gives. Golden questions run here only in the property test below: with the
    fake embedder their vectors are noise. `make eval` runs golden x matrix for real."""
    matrix = entitlement_matrix(PERSONAS, MODULES)
    report = env.run(
        run_permission_suite(
            env.retriever,
            RERANKER,
            index_version=corpus["version"],
            entitlements=matrix,
            queries=corpus["self"],
            chunk_modules=corpus["modules"],
        )
    )
    assert report.violations == [], (
        f"{len(report.violations)} leaks, first: {report.violations[:3]}"
    )
    assert report.vacuous == [], f"{len(report.vacuous)} vacuous, first: {report.vacuous[:3]}"
    assert report.searches == len(matrix) * len(corpus["self"])
    assert report.checked > 50_000, "the suite must actually look at candidates"


def test_self_retrieval_puts_restricted_chunks_closest_and_they_still_never_leak(
    env: Env, corpus: dict[str, Any]
) -> None:
    """Querying a restricted chunk's own text makes it the best match on both vector and
    keyword search for anyone; a sales rep at globex (no campaigns) must still not see it."""
    rep = Entitlement("sales_rep@globex", PERSONAS["sales_rep@globex"])
    restricted = [
        q for q in corpus["self"] if not set(corpus["modules"][q.expect_chunk]) <= rep.allowed
    ]
    assert restricted, "the corpus must have chunks this persona can't see"
    report = env.run(
        run_permission_suite(
            env.retriever,
            None,
            index_version=corpus["version"],
            entitlements=[rep],
            queries=restricted,
            chunk_modules=corpus["modules"],
        )
    )
    assert report.passed and report.checked > 0


# --- property: the SQL filter means exactly `set(modules) <= allowed` -----------------------

TAGS = st.lists(st.sampled_from(["core", "a", "b", "c"]), min_size=1, max_size=3)  # dupes allowed
ALLOWED = st.frozensets(st.sampled_from(["core", "a", "b", "c", "A", "a ", "*"]), max_size=5)


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(tags=st.lists(TAGS, min_size=1, max_size=20), allowed=ALLOWED)
def test_search_returns_exactly_the_chunks_all_of_whose_modules_are_allowed(
    env: Env, pg_url: str, tags: list[list[str]], allowed: frozenset[str]
) -> None:
    rng = np.random.default_rng(len(tags))
    with psycopg.connect(pg_url, autocommit=True) as conn:
        register_vector(conn)
        row = conn.execute(
            "INSERT INTO index_versions (status, recipe) VALUES ('gate', '{}') "
            "RETURNING index_version"
        ).fetchone()
        assert row is not None
        version = int(row[0])
        for i, modules in enumerate(tags):
            v = rng.standard_normal(1024).astype(np.float32)
            conn.execute(
                "INSERT INTO chunks (index_version, chunk_id, doc_id, doc_version, anchor, part, "
                "breadcrumb, content, modules, token_count, oversized, content_hash, embedding) "
                "VALUES (%s, %s, 'p', 1, %s, 0, 'P', 'words', %s, 1, false, %s, %s)",
                (version, f"p#s{i}:0", f"s{i}", modules, f"h{i}", v / np.linalg.norm(v)),
            )
    got = env.run(env.retriever.search("words", allowed, 100, index_version=version))
    expected = {f"p#s{i}:0" for i, modules in enumerate(tags) if set(modules) <= allowed}
    assert {c.chunk_id for c in got} == expected


# --- property: random entitlement sets on the real corpus -----------------------------------


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    allowed=st.frozensets(st.sampled_from([*MODULES, *BOGUS_MODULES])),
    pick=st.integers(min_value=0),
)
def test_random_entitlements_on_the_corpus_never_leak_and_find_their_own_chunks(
    env: Env, corpus: dict[str, Any], allowed: frozenset[str], pick: int
) -> None:
    queries = [*GOLDEN, *corpus["self"]]
    query = queries[pick % len(queries)]
    report = env.run(
        run_permission_suite(
            env.retriever,
            RERANKER,
            index_version=corpus["version"],
            entitlements=[Entitlement("random", allowed)],
            queries=[query],
            chunk_modules=corpus["modules"],
        )
    )
    assert report.passed, (report.violations, report.vacuous)
