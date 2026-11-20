"""Rerank score cache (S2.3.1), in Postgres like the embedding cache.

A cross-encoder score depends only on (reranker, query, chunk text), never on who is
asking, so one score serves every persona and every later run. Keyed by the chunk's
content_hash, so editing a doc only rescores that doc's changed chunks.
"""

import hashlib
from collections.abc import Sequence

from psycopg_pool import AsyncConnectionPool

from chatbot.ports.retriever import Candidate
from chatbot.retrieval.rerank import CrossEncoderReranker, order


class CachingReranker:
    def __init__(self, inner: CrossEncoderReranker, pool: AsyncConnectionPool) -> None:
        self._inner = inner
        self._pool = pool

    @property
    def key(self) -> str:
        return self._inner.key

    async def rerank(self, query: str, candidates: Sequence[Candidate], k: int) -> list[Candidate]:
        if k < 1:
            raise ValueError(f"k must be at least 1, got {k}")
        if not candidates:
            return []
        if any(not c.content_hash for c in candidates):
            raise ValueError("every candidate needs a content_hash to be cached safely")
        query_sha = hashlib.sha256(query.encode()).hexdigest()
        hashes = list(dict.fromkeys(c.content_hash for c in candidates))
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT content_hash, score FROM rerank_cache "
                "WHERE reranker = %s AND query_sha = %s AND content_hash = ANY(%s)",
                (self.key, query_sha, hashes),
            )
            cached: dict[str, float] = {h: float(s) for h, s in await cur.fetchall()}
            missing = list(
                {c.content_hash: c for c in candidates if c.content_hash not in cached}.values()
            )
            if missing:
                fresh = await self._inner.scores(query, missing)
                async with conn.cursor() as w:
                    await w.executemany(
                        "INSERT INTO rerank_cache (reranker, query_sha, content_hash, score) "
                        "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                        [
                            (self.key, query_sha, c.content_hash, s)
                            for c, s in zip(missing, fresh, strict=True)
                        ],
                    )
                cached.update({c.content_hash: s for c, s in zip(missing, fresh, strict=True)})
        return order(candidates, [cached[c.content_hash] for c in candidates], k)
