"""Filtered hybrid search on Postgres (S2.2.1). Design: docs/backlog.md, "S2.2.1 design".

One fixed SQL statement per query: exact vector search and keyword search, each with
`modules <@ %(allowed)s` inside it, before its ORDER BY ... LIMIT (rule 2). The two
ranked lists are fused in Python by `fusion.rrf`.
"""

from psycopg_pool import AsyncConnectionPool

from chatbot.ports.embedder import Embedder
from chatbot.ports.retriever import Candidate

PER_LIST = 50  # candidates from each search before fusion

HYBRID_SQL = ""  # S2.2.1: written with the implementation, after test review
LIVE_VERSION_SQL = ""


class PgHybridRetriever:
    def __init__(
        self, pool: AsyncConnectionPool, embedder: Embedder, *, per_list: int = PER_LIST
    ) -> None:
        raise NotImplementedError("S2.2.1: implement after the tests are reviewed")

    async def live_version(self) -> int:
        raise NotImplementedError

    async def search(
        self, query: str, allowed_modules: frozenset[str], k: int, *, index_version: int
    ) -> list[Candidate]:
        raise NotImplementedError
