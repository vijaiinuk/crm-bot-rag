"""S2.2.1: done when hybrid search returns only chunks whose modules are all allowed.

The filter tests come first (CLAUDE.md rules 2 and 5). The SQL-text tests need no
database; the rest insert chunks with hand-placed vectors into chatbot_test, so a test
can put restricted decoys exactly where a post-filtering bug would be caught.
"""

import itertools
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

import numpy as np
import psycopg
import pytest
from pgvector.psycopg import register_vector, register_vector_async
from psycopg_pool import AsyncConnectionPool

from chatbot.ports.retriever import Candidate, NoLiveIndex
from chatbot.retrieval.hybrid import HYBRID_SQL, PER_LIST, PgHybridRetriever

DIM = 1024


# --- the SQL itself: no database needed -----------------------------------------------------


def _part(sql: str, start: str, end: str | None) -> str:
    body = sql[sql.index(start) :]
    return body[: body.index(end)] if end else body


def test_the_filter_is_inside_both_searches_before_their_limit() -> None:
    """Rule 2: filter before ranking. A filter after LIMIT would be post-filtering."""
    vec = _part(HYBRID_SQL, "vec AS (", "kw AS (")
    kw = _part(HYBRID_SQL, "kw AS (", None)
    for name, part in (("vector", vec), ("keyword", kw)):
        assert "modules <@ %(allowed)s" in part, f"{name} search has no module filter"
        assert part.index("modules <@") < part.index("LIMIT"), f"{name}: filter after LIMIT"
        assert "index_version = %(version)s" in part, f"{name} search is not version-pinned"
    assert HYBRID_SQL.count("modules <@ %(allowed)s") == 2


def test_the_sql_is_fixed_text_with_bound_parameters() -> None:
    """Module names are bound, never formatted into the SQL; the version is passed in."""
    for param in ("%(allowed)s", "%(version)s", "%(qvec)s", "%(qtext)s", "%(n)s"):
        assert param in HYBRID_SQL, f"{param} is not bound"
    assert "{" not in HYBRID_SQL and "active_index" not in HYBRID_SQL
    assert "websearch_to_tsquery" not in HYBRID_SQL, "keyword matching ORs the words"


# --- fixtures: a hand-built index -----------------------------------------------------------


def unit(i: int) -> np.ndarray[Any, Any]:
    v = np.zeros(DIM, dtype=np.float32)
    v[i] = 1.0
    return v


def near(i: int, j: int, eps: float = 0.01) -> np.ndarray[Any, Any]:
    """Almost exactly unit(i): cosine similarity about 0.99995."""
    v = unit(i) + eps * unit(j)
    return (v / np.linalg.norm(v)).astype(np.float32)


class StubEmbedder:
    """Embeds every query as one fixed vector."""

    key = "stub@1"
    dim = DIM

    def __init__(self, query_vector: np.ndarray[Any, Any]) -> None:
        self.query_vector = [float(x) for x in query_vector]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.query_vector for _ in texts]

    def count_tokens(self, text: str) -> int:
        return len(text.split())


class Index:
    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self.conn = conn

    def version(self, *, live: bool = True) -> int:
        row = self.conn.execute(
            "INSERT INTO index_versions (status, recipe) VALUES (%s, '{}') RETURNING index_version",
            ("live" if live else "gate",),
        ).fetchone()
        assert row is not None
        if live:
            self.conn.execute(
                "INSERT INTO active_index (alias, index_version) VALUES ('live', %s) "
                "ON CONFLICT (alias) DO UPDATE SET index_version = EXCLUDED.index_version",
                (row[0],),
            )
        return int(row[0])

    def chunk(
        self,
        version: int,
        chunk_id: str,
        modules: list[str],
        vector: np.ndarray[Any, Any],
        content: str = "filler",
    ) -> None:
        doc_id, rest = chunk_id.split("#")
        anchor = rest.split(":")[0]
        self.conn.execute(
            "INSERT INTO chunks (index_version, chunk_id, doc_id, doc_version, anchor, part, "
            "breadcrumb, content, modules, token_count, oversized, content_hash, embedding) "
            "VALUES (%s, %s, %s, 1, %s, 0, %s, %s, %s, 1, false, %s, %s)",
            (
                version,
                chunk_id,
                doc_id,
                anchor,
                f"{doc_id} > {anchor}",
                content,
                modules,
                chunk_id,
                vector,
            ),
        )


@pytest.fixture
def index(pg_url: str) -> Iterator[Index]:
    with psycopg.connect(pg_url, autocommit=True) as conn:
        register_vector(conn)
        conn.execute(
            "TRUNCATE chunks, embedding_cache, index_promotions, active_index, index_versions "
            "RESTART IDENTITY CASCADE"
        )
        yield Index(conn)


@pytest.fixture
async def pool(pg_url: str) -> AsyncIterator[AsyncConnectionPool]:
    async with AsyncConnectionPool(
        pg_url, configure=register_vector_async, min_size=1, max_size=2
    ) as p:
        yield p


def retriever(
    pool: AsyncConnectionPool, query_vector: np.ndarray[Any, Any], per_list: int = PER_LIST
) -> PgHybridRetriever:
    return PgHybridRetriever(pool, StubEmbedder(query_vector), per_list=per_list)


def ids(candidates: list[Candidate]) -> list[str]:
    return [c.chunk_id for c in candidates]


# --- the filter: rules 2 and 5 --------------------------------------------------------------


@pytest.mark.db
async def test_filter_before_ranking_finds_an_allowed_chunk_behind_closer_restricted_ones(
    index: Index, pool: AsyncConnectionPool
) -> None:
    """More restricted decoys than each search keeps, all closer to the query in both
    vector and keyword terms. Filtering the top results afterwards would return nothing."""
    v = index.version()
    for i in range(PER_LIST + 10):
        index.chunk(v, f"secret#d{i}:0", ["reports"], near(0, i + 1), "pipeline forecast revenue")
    index.chunk(v, "ok#far:0", ["core"], unit(900), "unrelated words entirely")
    got = await retriever(pool, unit(0)).search(
        "pipeline forecast revenue", frozenset({"core"}), 5, index_version=v
    )
    assert ids(got) == ["ok#far:0"]


TAGGED = {
    "t#core:0": ["core"],
    "t#a:0": ["a"],
    "t#b:0": ["b"],
    "t#a-b:0": ["a", "b"],
    "t#a-core:0": ["a", "core"],
    "t#b-core:0": ["b", "core"],
    "t#a-b-core:0": ["a", "b", "core"],
}


@pytest.mark.db
async def test_every_allowed_set_sees_exactly_the_chunks_all_of_whose_modules_it_holds(
    index: Index, pool: AsyncConnectionPool
) -> None:
    """Every subset of {core, a, b}: nothing leaks, and nothing visible is filtered out."""
    v = index.version()
    for n, (chunk_id, modules) in enumerate(TAGGED.items(), start=1):
        index.chunk(v, chunk_id, modules, unit(n), "same words everywhere")
    r = retriever(pool, unit(0))
    for size in range(4):
        for allowed in map(frozenset, itertools.combinations(["core", "a", "b"], size)):
            got = await r.search("same words", allowed, 100, index_version=v)
            expected = {cid for cid, mods in TAGGED.items() if set(mods) <= allowed}
            assert set(ids(got)) == expected, f"allowed={sorted(allowed)}"
            assert all(set(c.modules) <= allowed for c in got)


@pytest.mark.db
async def test_a_chunk_needs_all_its_modules(index: Index, pool: AsyncConnectionPool) -> None:
    """Rule 5, on its own: holding `a` is not enough for a chunk tagged [a, b]."""
    v = index.version()
    index.chunk(v, "t#a-b:0", ["a", "b"], unit(0), "deal campaign trigger")
    r = retriever(pool, unit(0))
    assert await r.search("deal campaign", frozenset({"a", "core"}), 10, index_version=v) == []
    assert ids(await r.search("deal campaign", frozenset({"a", "b"}), 10, index_version=v)) == [
        "t#a-b:0"
    ]


@pytest.mark.db
async def test_the_keyword_search_applies_the_same_filter(
    index: Index, pool: AsyncConnectionPool
) -> None:
    """A restricted chunk that is the only keyword match is still never returned."""
    v = index.version()
    index.chunk(v, "secret#zebra:0", ["reports"], unit(1), "zebra invoice reconciliation")
    index.chunk(v, "ok#plain:0", ["core"], unit(2), "nothing relevant here")
    r = retriever(pool, unit(0))
    got = await r.search("zebra reconciliation", frozenset({"core"}), 10, index_version=v)
    assert ids(got) == ["ok#plain:0"] and got[0].kw_rank is None
    both = await r.search(
        "zebra reconciliation", frozenset({"core", "reports"}), 10, index_version=v
    )
    assert next(c for c in both if c.chunk_id == "secret#zebra:0").kw_rank == 1


@pytest.mark.db
async def test_an_empty_allowed_set_sees_nothing(index: Index, pool: AsyncConnectionPool) -> None:
    v = index.version()
    index.chunk(v, "t#core:0", ["core"], unit(0), "anything")
    assert await retriever(pool, unit(0)).search("anything", frozenset(), 10, index_version=v) == []


# --- hybrid behaviour -----------------------------------------------------------------------


@pytest.mark.db
async def test_keyword_search_finds_an_exact_term_the_vector_search_misses(
    index: Index, pool: AsyncConnectionPool
) -> None:
    v = index.version()
    index.chunk(v, "d#close-1:0", ["core"], near(0, 1), "general overview")
    index.chunk(v, "d#close-2:0", ["core"], near(0, 2), "another overview")
    index.chunk(v, "d#exact:0", ["core"], unit(500), "set the probability field")
    got = await retriever(pool, unit(0), per_list=2).search(
        "where is the probability setting", frozenset({"core"}), 10, index_version=v
    )
    exact = next(c for c in got if c.chunk_id == "d#exact:0")
    assert (exact.vec_rank, exact.kw_rank) == (None, 1)


@pytest.mark.db
async def test_candidates_carry_the_chunk_their_ranks_and_the_index_version(
    index: Index, pool: AsyncConnectionPool
) -> None:
    v = index.version()
    index.chunk(v, "deals-x#move:0", ["deals", "core"], unit(0), "move a deal between stages")
    index.chunk(v, "deals-x#other:0", ["deals"], unit(1), "something else")
    got = await retriever(pool, unit(0)).search(
        "move a deal", frozenset({"core", "deals"}), 10, index_version=v
    )
    top = got[0]
    assert (top.chunk_id, top.doc_id, top.anchor) == ("deals-x#move:0", "deals-x", "move")
    assert top.modules == ("deals", "core") and top.index_version == v
    assert top.breadcrumb == "deals-x > move" and top.content == "move a deal between stages"
    assert (top.vec_rank, top.kw_rank) == (1, 1)
    assert [c.score for c in got] == sorted((c.score for c in got), reverse=True)


@pytest.mark.db
async def test_k_caps_the_results(index: Index, pool: AsyncConnectionPool) -> None:
    v = index.version()
    for i in range(7):
        index.chunk(v, f"d#s{i}:0", ["core"], unit(i), "words")
    got = await retriever(pool, unit(0)).search("words", frozenset({"core"}), 3, index_version=v)
    assert len(got) == 3


@pytest.mark.db
async def test_a_question_of_only_stop_words_still_gets_vector_results(
    index: Index, pool: AsyncConnectionPool
) -> None:
    v = index.version()
    index.chunk(v, "d#s:0", ["core"], unit(0), "how do I do this")
    got = await retriever(pool, unit(0)).search(
        "how do i do this", frozenset({"core"}), 10, index_version=v
    )
    assert ids(got) == ["d#s:0"] and got[0].kw_rank is None


# --- index versions -------------------------------------------------------------------------


@pytest.mark.db
async def test_search_uses_only_the_version_it_is_given(
    index: Index, pool: AsyncConnectionPool
) -> None:
    live = index.version()
    index.chunk(live, "d#a:0", ["core"], unit(1), "live text")
    staged = index.version(live=False)
    index.chunk(staged, "d#a:0", ["core"], unit(0), "staged text")
    r = retriever(pool, unit(0))
    assert await r.live_version() == live
    got = await r.search("text", frozenset({"core"}), 10, index_version=live)
    assert [(c.content, c.index_version) for c in got] == [("live text", live)]


@pytest.mark.db
async def test_no_live_index_is_an_error_not_an_empty_answer(
    index: Index, pool: AsyncConnectionPool
) -> None:
    index.version(live=False)
    with pytest.raises(NoLiveIndex):
        await retriever(pool, unit(0)).live_version()
