"""Evaluate one index version (S2.4.1): the step `make eval` and the publish gate share.

Retrieval metrics over the golden set and, when entitlement sets are given, the
permission suite (golden questions + self-retrieval, hybrid stage). Raises
OrphanLabels before searching if a golden label matches no chunk of the version.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from psycopg_pool import AsyncConnectionPool

from chatbot.evals import permissions
from chatbot.evals.golden import GoldenQuestion
from chatbot.evals.labels import ChunkRow, label_index
from chatbot.evals.retrieval import RunResult, run_retrieval_eval
from chatbot.ports.reranker import Reranker
from chatbot.ports.retriever import Retriever


@dataclass
class VersionEval:
    version: int
    recipe: dict[str, Any]
    run: RunResult
    permissions: permissions.PermissionReport | None
    doc_modules: dict[str, tuple[str, ...]]  # doc_id -> modules, as indexed
    queries: int  # permission-suite queries (golden + self-retrieval)


class VersionNotFound(Exception):
    pass


async def evaluate_version(
    pool: AsyncConnectionPool,
    version: int,
    *,
    retriever: Retriever,
    reranker: Reranker,
    golden: Sequence[GoldenQuestion],
    personas: Mapping[str, frozenset[str]],
    threshold: float,
    entitlements: Sequence[permissions.Entitlement] | None = None,
    permission_queries: Sequence[permissions.Query] | None = None,
) -> VersionEval:
    """`permission_queries=None` (every real caller) means golden + every chunk's
    self-retrieval query; tests of the gate's wiring may pass a smaller set."""
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT chunk_id, doc_id, anchor, parent_anchor, modules, "
            "breadcrumb || E'\\n\\n' || content FROM chunks WHERE index_version = %s "
            "ORDER BY chunk_id",
            (version,),
        )
        fetched = await cur.fetchall()
        row = await (
            await conn.execute(
                "SELECT recipe FROM index_versions WHERE index_version = %s", (version,)
            )
        ).fetchone()
    if row is None or not fetched:
        raise VersionNotFound(f"index version {version} does not exist or has no chunks")

    chunk_modules = {r[0]: tuple(r[4]) for r in fetched}
    run = await run_retrieval_eval(
        golden,
        personas,
        retriever,
        reranker,
        label_index(ChunkRow(*r[:4]) for r in fetched),
        index_version=version,
        threshold=threshold,
    )
    perm = None
    queries = 0
    if entitlements is not None:
        if permission_queries is not None:
            query_list = list(permission_queries)
        else:
            query_list = [permissions.Query(q.id, q.question) for q in golden]
            query_list += permissions.self_retrieval_queries([(r[0], r[5]) for r in fetched])
        queries = len(query_list)
        # Hybrid stage only: the reranker can only reorder its input (unit tested), and
        # reranking hundreds of long self-retrieval queries would take many minutes.
        perm = await permissions.run_permission_suite(
            retriever,
            None,
            index_version=version,
            entitlements=entitlements,
            queries=query_list,
            chunk_modules=chunk_modules,
        )
    return VersionEval(
        version=version,
        recipe=row[0],
        run=run,
        permissions=perm,
        doc_modules={r[1]: tuple(r[4]) for r in fetched},
        queries=queries,
    )
