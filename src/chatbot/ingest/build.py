"""Build, promote and roll back index versions (S2.1.3).

    build_index  validated docs -> chunks -> embeddings (cache first) -> a complete
                 new index version with status `gate`. Never touches the live alias.
    promote      repoint an alias at a complete version, atomically.
    rollback     undo the alias's last repoint.

Fail closed: anything wrong before writing aborts with nothing written; anything
wrong while writing marks the version `failed` and leaves the live index alone.
Connections must be in autocommit mode; every step opens its own transaction.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from chatbot.ingest.chunker import Chunk, Chunker
from chatbot.ingest.validate import IngestAborted, ValidDoc
from chatbot.ports.catalogue import ModuleCatalogue
from chatbot.ports.embedder import Embedder

PARSER_VERSION = 1  # validator + anchors; bump when either changes what they accept or produce
LIVE = "live"


class BuildFailed(Exception):
    """Writing the index failed. The version is marked `failed`; nothing went live."""

    def __init__(self, index_version: int, cause: BaseException) -> None:
        super().__init__(f"index version {index_version} failed: {cause}")
        self.index_version = index_version


class PromotionError(Exception):
    """A promote or rollback was refused. The alias is unchanged."""


@dataclass(frozen=True, slots=True)
class BuildResult:
    index_version: int
    doc_count: int
    chunk_count: int
    embedded: int  # chunks whose embedding was computed in this build
    reused: int  # chunks whose embedding came from the cache
    corpus_sha: str


@dataclass(frozen=True, slots=True)
class VersionRow:
    index_version: int
    status: str
    chunk_count: int | None
    embedded: int | None
    reused: int | None
    ungated: bool
    created_at: datetime
    error: str | None
    aliases: tuple[str, ...]


def _require_autocommit(conn: psycopg.Connection[Any]) -> None:
    if not conn.autocommit:
        raise ValueError("pass an autocommit connection; each step opens its own transaction")


def corpus_sha(docs: Sequence[ValidDoc]) -> str:
    h = hashlib.sha256()
    for d in sorted(docs, key=lambda d: d.doc_id):
        h.update(f"{d.doc_id}:{d.sha256}\n".encode())
    return h.hexdigest()


def build_index(
    conn: psycopg.Connection[Any],
    docs: Sequence[ValidDoc],
    *,
    chunker: Chunker,
    embedder: Embedder,
    catalogue: ModuleCatalogue,
) -> BuildResult:
    _require_autocommit(conn)
    register_vector(conn)

    # 1. Everything that can be checked without writing is checked first.
    if not docs:
        raise IngestAborted(["no docs: refusing to build an empty index"])
    chunks = [c for d in docs for c in chunker.chunk(d)]
    unknown = sorted({m for c in chunks for m in c.modules} - set(catalogue.modules))
    if unknown:
        raise IngestAborted([f"modules not in the module catalogue: {unknown}"])
    if any(not c.modules for c in chunks):
        raise IngestAborted(["a chunk has no modules"])  # unreachable after validation

    recipe = {
        "parser_version": PARSER_VERSION,
        "chunker_config_hash": chunker.config_hash,
        "embed_model": embedder.key,
        "embed_dim": embedder.dim,
    }
    sha = corpus_sha(docs)
    with conn.transaction():
        row = conn.execute(
            "INSERT INTO index_versions (recipe, corpus_sha, doc_count) VALUES (%s, %s, %s) "
            "RETURNING index_version",
            (json.dumps(recipe), sha, len(docs)),
        ).fetchone()
    if row is None:
        raise RuntimeError("INSERT ... RETURNING returned no row")
    version: int = row[0]

    # 2. Write the complete version in one transaction, or mark it failed.
    try:
        with conn.transaction():
            vectors, embedded = _embeddings(conn, chunks, embedder)
            _sync_catalogue(conn, catalogue)
            _insert_chunks(conn, version, chunks, vectors)
            conn.execute(
                "UPDATE index_versions SET status = 'gate', chunk_count = %s, embedded = %s, "
                "reused = %s, finished_at = now() WHERE index_version = %s",
                (len(chunks), embedded, len(chunks) - embedded, version),
            )
    except Exception as e:
        with conn.transaction():
            conn.execute(
                "UPDATE index_versions SET status = 'failed', error = %s, finished_at = now() "
                "WHERE index_version = %s",
                (f"{type(e).__name__}: {e}", version),
            )
        raise BuildFailed(version, e) from e
    return BuildResult(version, len(docs), len(chunks), embedded, len(chunks) - embedded, sha)


def _embeddings(
    conn: psycopg.Connection[Any], chunks: Sequence[Chunk], embedder: Embedder
) -> tuple[dict[str, np.ndarray[Any, Any]], int]:
    """A vector per content hash: cached ones reused, missing ones embedded and cached."""
    hashes = sorted({c.content_hash for c in chunks})
    cached: dict[str, np.ndarray[Any, Any]] = {
        h: v
        for h, v in conn.execute(
            "SELECT content_hash, embedding FROM embedding_cache "
            "WHERE embed_model = %s AND content_hash = ANY(%s)",
            (embedder.key, hashes),
        ).fetchall()
    }
    text_of = {c.content_hash: c.embed_text for c in chunks}
    missing = [h for h in hashes if h not in cached]
    fresh = embedder.embed([text_of[h] for h in missing])
    if len(fresh) != len(missing):
        raise ValueError(f"embedder returned {len(fresh)} vectors for {len(missing)} texts")
    for h, v in zip(missing, fresh, strict=True):
        if len(v) != embedder.dim:
            raise ValueError(f"embedder returned a {len(v)}-dim vector, expected {embedder.dim}")
        cached[h] = np.asarray(v, dtype=np.float32)
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO embedding_cache (content_hash, embed_model, embedding) "
            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            [(h, embedder.key, cached[h]) for h in missing],
        )
    new = set(missing)
    embedded = sum(1 for c in chunks if c.content_hash in new)
    return cached, embedded


def _sync_catalogue(conn: psycopg.Connection[Any], catalogue: ModuleCatalogue) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO module_catalogue (module, display_name, description) VALUES (%s, %s, %s) "
            "ON CONFLICT (module) DO UPDATE SET display_name = EXCLUDED.display_name, "
            "description = EXCLUDED.description, updated_at = now()",
            [(m.name, m.display_name, m.description) for m in catalogue.modules.values()],
        )


def _insert_chunks(
    conn: psycopg.Connection[Any],
    version: int,
    chunks: Sequence[Chunk],
    vectors: dict[str, np.ndarray[Any, Any]],
) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO chunks (index_version, chunk_id, doc_id, doc_version, anchor, "
            "parent_anchor, part, breadcrumb, content, modules, token_count, oversized, "
            "content_hash, embedding) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    version,
                    c.chunk_id,
                    c.doc_id,
                    c.doc_version,
                    c.anchor,
                    c.parent_anchor,
                    c.part,
                    c.breadcrumb,
                    c.text,
                    list(c.modules),
                    c.token_count,
                    c.oversized,
                    c.content_hash,
                    vectors[c.content_hash],
                )
                for c in chunks
            ],
        )


# --- promote and roll back ------------------------------------------------------------------


def promote(
    conn: psycopg.Connection[Any], index_version: int, *, alias: str = LIVE, ungated: bool = False
) -> None:
    """Point `alias` at a complete version. Until the S2.4.1 publish gate exists, this
    must be asked for explicitly with `ungated=True`, which is recorded on the version."""
    _require_autocommit(conn)
    if not ungated:
        raise PromotionError(
            "the publish gate (S2.4.1) does not exist yet: promote with ungated=True "
            "(make ingest does), and it is recorded on the version"
        )
    with conn.transaction():
        conn.execute(
            "UPDATE index_versions SET ungated = true WHERE index_version = %s", (index_version,)
        )
        _repoint(conn, alias, index_version, "promote")


def rollback(conn: psycopg.Connection[Any], *, alias: str = LIVE) -> int:
    """Undo the alias's last repoint; returns the version now live. Twice = redo."""
    _require_autocommit(conn)
    with conn.transaction():
        current = _current(conn, alias)
        if current is None:
            raise PromotionError(f"alias {alias!r} points nowhere; nothing to roll back")
        row = conn.execute(
            "SELECT from_version FROM index_promotions WHERE alias = %s AND to_version = %s "
            "ORDER BY id DESC LIMIT 1",
            (alias, current),
        ).fetchone()
        if row is None or row[0] is None:
            raise PromotionError(f"version {current} was the first on {alias!r}; no earlier one")
        _repoint(conn, alias, row[0], "rollback")
        return int(row[0])


def _current(conn: psycopg.Connection[Any], alias: str) -> int | None:
    row = conn.execute(
        "SELECT index_version FROM active_index WHERE alias = %s FOR UPDATE", (alias,)
    ).fetchone()
    return None if row is None else int(row[0])


def _repoint(conn: psycopg.Connection[Any], alias: str, to: int, reason: str) -> None:
    """Inside a transaction: move the alias, update statuses, record the history."""
    row = conn.execute(
        "SELECT status FROM index_versions WHERE index_version = %s FOR UPDATE", (to,)
    ).fetchone()
    if row is None:
        raise PromotionError(f"no index version {to}")
    current = _current(conn, alias)
    if current == to:
        raise PromotionError(f"version {to} is already {alias!r}")
    if row[0] not in ("gate", "superseded"):
        raise PromotionError(f"version {to} is {row[0]!r}; only complete versions can go live")
    if current is not None:
        conn.execute(
            "UPDATE index_versions SET status = 'superseded' WHERE index_version = %s", (current,)
        )
    conn.execute(
        "UPDATE index_versions SET status = 'live', promoted_at = now() WHERE index_version = %s",
        (to,),
    )
    conn.execute(
        "INSERT INTO active_index (alias, index_version) VALUES (%s, %s) "
        "ON CONFLICT (alias) DO UPDATE SET index_version = EXCLUDED.index_version, "
        "updated_at = now()",
        (alias, to),
    )
    conn.execute(
        "INSERT INTO index_promotions (alias, from_version, to_version, reason) "
        "VALUES (%s, %s, %s, %s)",
        (alias, current, to, reason),
    )


def list_versions(conn: psycopg.Connection[Any]) -> list[VersionRow]:
    rows = conn.execute(
        "SELECT v.index_version, v.status, v.chunk_count, v.embedded, v.reused, v.ungated, "
        "v.created_at, v.error, "
        "coalesce(array_agg(a.alias) FILTER (WHERE a.alias IS NOT NULL), '{}') "
        "FROM index_versions v LEFT JOIN active_index a USING (index_version) "
        "GROUP BY v.index_version ORDER BY v.index_version"
    ).fetchall()
    return [
        VersionRow(
            index_version=r[0],
            status=r[1],
            chunk_count=r[2],
            embedded=r[3],
            reused=r[4],
            ungated=r[5],
            created_at=r[6],
            error=r[7],
            aliases=tuple(r[8]),
        )
        for r in rows
    ]
