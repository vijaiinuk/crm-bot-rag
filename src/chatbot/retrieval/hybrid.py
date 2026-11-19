"""Filtered hybrid search on Postgres (S2.2.1). Design: docs/backlog.md, "S2.2.1 design".

One fixed SQL statement per query: exact vector search and keyword search, each with
`modules <@ %(allowed)s` inside it, before its ORDER BY ... LIMIT (rule 2). The two
ranked lists are fused in Python by `fusion.rrf`.

The pool's connections must have pgvector's types registered: build it with
`make_pool`, or pass `configure=register_vector_async` yourself.
"""

import asyncio

import numpy as np
from pgvector.psycopg import register_vector_async
from psycopg_pool import AsyncConnectionPool

from chatbot.ports.embedder import Embedder
from chatbot.ports.retriever import Candidate, NoLiveIndex
from chatbot.retrieval.fusion import DEFAULT_K, rrf

PER_LIST = 50  # candidates from each search before fusion

# Keyword matching ORs the question's stemmed words. plainto_tsquery stems with the
# 'english' config and prints a correctly quoted query ('deal' & 'stage'); swapping
# '&' for '|' and parsing it back with 'simple' (no second stemming) gives the OR query.
# A question of only stop words gives an empty query, which matches nothing.
HYBRID_SQL = """
WITH q AS (
  SELECT to_tsquery('simple', replace(plainto_tsquery('english', %(qtext)s)::text, ' & ', ' | '))
         AS tsq
),
vec AS (
  SELECT chunk_id, row_number() OVER (ORDER BY embedding <=> %(qvec)s, chunk_id) AS rank
  FROM chunks
  WHERE index_version = %(version)s
    AND modules <@ %(allowed)s::text[]
  ORDER BY embedding <=> %(qvec)s, chunk_id
  LIMIT %(n)s
),
kw AS (
  SELECT chunk_id, row_number() OVER (ORDER BY ts_rank_cd(tsv, q.tsq) DESC, chunk_id) AS rank
  FROM chunks, q
  WHERE index_version = %(version)s
    AND modules <@ %(allowed)s::text[]
    AND tsv @@ q.tsq
  ORDER BY ts_rank_cd(tsv, q.tsq) DESC, chunk_id
  LIMIT %(n)s
)
SELECT u.source, u.rank, c.chunk_id, c.doc_id, c.anchor, c.breadcrumb, c.content, c.modules
FROM (
  SELECT 'vec' AS source, chunk_id, rank FROM vec
  UNION ALL
  SELECT 'kw' AS source, chunk_id, rank FROM kw
) u
JOIN chunks c ON c.index_version = %(version)s AND c.chunk_id = u.chunk_id
ORDER BY u.source, u.rank
"""

LIVE_VERSION_SQL = "SELECT index_version FROM active_index WHERE alias = 'live'"


def make_pool(conninfo: str, *, min_size: int = 1, max_size: int = 4) -> AsyncConnectionPool:
    """A pool whose connections understand pgvector's `vector` type. Open it before use."""
    return AsyncConnectionPool(
        conninfo,
        configure=register_vector_async,
        min_size=min_size,
        max_size=max_size,
        open=False,
    )


class PgHybridRetriever:
    def __init__(
        self,
        pool: AsyncConnectionPool,
        embedder: Embedder,
        *,
        per_list: int = PER_LIST,
        rrf_k: int = DEFAULT_K,
    ) -> None:
        if per_list < 1:
            raise ValueError(f"per_list must be at least 1, got {per_list}")
        self._pool = pool
        self._embedder = embedder
        self._per_list = per_list
        self._rrf_k = rrf_k

    async def live_version(self) -> int:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(LIVE_VERSION_SQL)).fetchone()
        if row is None:
            raise NoLiveIndex("no index version is live: run `make ingest`")
        return int(row[0])

    async def search(
        self, query: str, allowed_modules: frozenset[str], k: int, *, index_version: int
    ) -> list[Candidate]:
        if k < 1:
            raise ValueError(f"k must be at least 1, got {k}")
        if not allowed_modules:
            return []  # fail closed; the SQL would match nothing anyway
        # The embedder is CPU/GPU-bound and blocking: keep it off the event loop.
        [qvec] = await asyncio.to_thread(self._embedder.embed, [query])
        params = {
            "qtext": query,
            "qvec": np.asarray(qvec, dtype=np.float32),
            "allowed": sorted(allowed_modules),
            "version": index_version,
            "n": self._per_list,
        }
        async with self._pool.connection() as conn:
            rows = await (await conn.execute(HYBRID_SQL, params)).fetchall()

        # Vector first: it is the stronger list (MRR 0.88 vs 0.68), so it wins ties.
        lists: dict[str, list[str]] = {"vec": [], "kw": []}
        chunk: dict[str, tuple[str, str, str, str, tuple[str, ...]]] = {}
        for source, _rank, chunk_id, doc_id, anchor, breadcrumb, content, modules in rows:
            lists[source].append(chunk_id)  # rows arrive ordered by source, then rank
            chunk[chunk_id] = (doc_id, anchor, breadcrumb, content, tuple(modules))
        return [
            Candidate(
                chunk_id=f.chunk_id,
                doc_id=chunk[f.chunk_id][0],
                anchor=chunk[f.chunk_id][1],
                breadcrumb=chunk[f.chunk_id][2],
                content=chunk[f.chunk_id][3],
                modules=chunk[f.chunk_id][4],
                index_version=index_version,
                vec_rank=f.ranks.get("vec"),
                kw_rank=f.ranks.get("kw"),
                score=f.score,
            )
            for f in rrf(lists, k=self._rrf_k)[:k]
        ]
