"""S2.1.3: done when two ingest runs produce two index versions, promote and rollback
work, and unchanged chunks reuse cached embeddings.

Runs the real 42-doc corpus against Postgres (`db` marker) with a fake embedder:
deterministic vectors from a hash of the text, so no model download is needed.
"""

import dataclasses
import hashlib
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
import pytest

from chatbot.adapters.local_catalogue import load_catalogue
from chatbot.ingest.build import (
    BuildFailed,
    PromotionError,
    build_index,
    list_versions,
    promote,
    rollback,
)
from chatbot.ingest.chunker import Chunker
from chatbot.ingest.validate import DocValidator, IngestAborted, ValidDoc, load_frontmatter_schema
from chatbot.ports.catalogue import ModuleCatalogue

ROOT = Path(__file__).parents[2]
CATALOGUE = load_catalogue(ROOT / "data" / "module_catalogue.yaml")
CORPUS = DocValidator(
    frozenset(CATALOGUE.modules),
    load_frontmatter_schema(ROOT / "data" / "spec" / "doc_frontmatter.schema.json"),
).read_corpus(ROOT / "data" / "docs")
CHUNKS = 124


class FakeEmbedder:
    def __init__(self, key: str = "fake-model@1", *, fail: bool = False) -> None:
        self.key = key
        self.dim = 1024
        self.fail = fail
        self.embedded: list[str] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self.fail:
            raise RuntimeError("embedding service exploded")
        self.embedded += texts
        out = []
        for t in texts:
            seed = int.from_bytes(hashlib.sha256((self.key + t).encode()).digest()[:8], "big")
            v = np.random.default_rng(seed).standard_normal(self.dim)
            out.append([float(x) for x in v / np.linalg.norm(v)])
        return out

    def count_tokens(self, text: str) -> int:
        return len(text.split())


def build(
    conn: psycopg.Connection[Any],
    docs: Sequence[ValidDoc] = CORPUS,
    embedder: FakeEmbedder | None = None,
    catalogue: ModuleCatalogue = CATALOGUE,
) -> Any:
    embedder = embedder or FakeEmbedder()
    chunker = Chunker(embedder.count_tokens, tokenizer_name=embedder.key)
    return build_index(conn, docs, chunker=chunker, embedder=embedder, catalogue=catalogue)


def one(conn: psycopg.Connection[Any], sql: str, *params: Any) -> Any:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return row[0]


@pytest.fixture
def conn(pg_url: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(pg_url, autocommit=True) as c:
        c.execute(
            "TRUNCATE chunks, embedding_cache, index_promotions, active_index, index_versions, "
            "module_catalogue RESTART IDENTITY CASCADE"
        )
        yield c


pytestmark = pytest.mark.db


# --- versions and the embedding cache -------------------------------------------------------


def test_two_builds_make_two_versions_and_the_second_reuses_every_embedding(
    conn: psycopg.Connection[Any],
) -> None:
    first = build(conn)
    assert (first.index_version, first.chunk_count, first.embedded, first.reused) == (
        1,
        CHUNKS,
        CHUNKS,
        0,
    )
    again = FakeEmbedder()
    second = build(conn, embedder=again)
    assert (second.index_version, second.embedded, second.reused) == (2, 0, CHUNKS)
    assert again.embedded == [], "nothing re-embedded"
    assert second.corpus_sha == first.corpus_sha
    assert [v.status for v in list_versions(conn)] == ["gate", "gate"], "builds never go live"
    assert one(conn, "SELECT count(*) FROM chunks") == 2 * CHUNKS
    assert one(conn, "SELECT count(*) FROM embedding_cache") == CHUNKS


def test_editing_one_section_re_embeds_only_that_chunk(conn: psycopg.Connection[Any]) -> None:
    build(conn)
    doc = next(d for d in CORPUS if d.doc_id == "deals-board-view")
    edited = dataclasses.replace(
        doc, body=doc.body.replace("Each pipeline has its own stages.", "Pipelines differ.")
    )
    docs = [edited if d is doc else d for d in CORPUS]
    embedder = FakeEmbedder()
    result = build(conn, docs, embedder)
    assert (result.embedded, result.reused) == (1, CHUNKS - 1)
    assert embedder.embedded[0].startswith("Using the pipeline board > Filter the board")


def test_a_different_embedding_model_re_embeds_everything(conn: psycopg.Connection[Any]) -> None:
    build(conn)
    result = build(conn, embedder=FakeEmbedder("other-model@2"))
    assert (result.embedded, result.reused) == (CHUNKS, 0)


# --- promote and rollback -------------------------------------------------------------------


def live(conn: psycopg.Connection[Any]) -> int:
    return int(one(conn, "SELECT index_version FROM active_index WHERE alias = 'live'"))


def test_promote_and_rollback_repoint_the_live_alias(conn: psycopg.Connection[Any]) -> None:
    v1, v2 = build(conn).index_version, build(conn).index_version
    promote(conn, v1, ungated=True)
    promote(conn, v2, ungated=True)
    assert live(conn) == v2
    assert {v.index_version: v.status for v in list_versions(conn)} == {
        v1: "superseded",
        v2: "live",
    }

    assert rollback(conn) == v1
    assert live(conn) == v1
    assert {v.index_version: v.status for v in list_versions(conn)} == {
        v1: "live",
        v2: "superseded",
    }
    assert rollback(conn) == v2, "rolling back a rollback is a redo"
    reasons = conn.execute(
        "SELECT from_version, to_version, reason FROM index_promotions ORDER BY id"
    ).fetchall()
    assert reasons == [
        (None, v1, "promote"),
        (v1, v2, "promote"),
        (v2, v1, "rollback"),
        (v1, v2, "rollback"),
    ]
    assert all(v.ungated for v in list_versions(conn)), "skipping the gate is recorded"


def test_rollback_needs_an_earlier_version(conn: psycopg.Connection[Any]) -> None:
    with pytest.raises(PromotionError, match="points nowhere"):
        rollback(conn)
    promote(conn, build(conn).index_version, ungated=True)
    with pytest.raises(PromotionError, match="no earlier one"):
        rollback(conn)


def test_promotion_is_refused_without_ungated_or_a_complete_version(
    conn: psycopg.Connection[Any],
) -> None:
    v1 = build(conn).index_version
    with pytest.raises(PromotionError, match="publish gate"):
        promote(conn, v1)
    with pytest.raises(PromotionError, match="no index version 99"):
        promote(conn, 99, ungated=True)
    with pytest.raises(BuildFailed):
        build(conn, embedder=FakeEmbedder(fail=True))
    with pytest.raises(PromotionError, match="'failed'"):
        promote(conn, 2, ungated=True)
    promote(conn, v1, ungated=True)
    with pytest.raises(PromotionError, match="already"):
        promote(conn, v1, ungated=True)
    assert live(conn) == v1


# --- fail closed ----------------------------------------------------------------------------


def test_a_module_missing_from_the_catalogue_aborts_with_nothing_written(
    conn: psycopg.Connection[Any],
) -> None:
    partial = ModuleCatalogue(
        {k: v for k, v in CATALOGUE.modules.items() if k != "deals"}, CATALOGUE.restricted_contact
    )
    with pytest.raises(IngestAborted, match="deals"):
        build(conn, catalogue=partial)
    assert one(conn, "SELECT count(*) FROM index_versions") == 0


def test_an_embedding_failure_marks_the_version_failed_and_leaves_live_alone(
    conn: psycopg.Connection[Any],
) -> None:
    v1 = build(conn).index_version
    promote(conn, v1, ungated=True)
    with pytest.raises(BuildFailed, match="exploded"):
        build(conn, embedder=FakeEmbedder("new-model@1", fail=True))
    failed = list_versions(conn)[-1]
    assert failed.status == "failed" and failed.error and "exploded" in failed.error
    assert (
        one(conn, "SELECT count(*) FROM chunks WHERE index_version = %s", failed.index_version) == 0
    )
    assert live(conn) == v1


def test_the_database_rejects_a_chunk_with_no_modules(conn: psycopg.Connection[Any]) -> None:
    v = build(conn).index_version
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO chunks SELECT index_version, 'x#y:0', doc_id, doc_version, anchor, "
            "parent_anchor, part, breadcrumb, content, '{}', required_permission, token_count, "
            "oversized, content_hash, embedding FROM chunks WHERE index_version = %s LIMIT 1",
            (v,),
        )


# --- what was written -----------------------------------------------------------------------


def test_chunks_carry_frontmatter_modules_and_searchable_text(
    conn: psycopg.Connection[Any],
) -> None:
    v = build(conn).index_version
    stored = dict(
        conn.execute(
            "SELECT DISTINCT doc_id, modules FROM chunks WHERE index_version = %s", (v,)
        ).fetchall()
    )
    assert stored == {d.doc_id: list(d.modules) for d in CORPUS}
    assert one(conn, "SELECT count(*) FROM chunks WHERE tsv = ''::tsvector") == 0
    hits = conn.execute(
        "SELECT chunk_id FROM chunks WHERE index_version = %s "
        "AND tsv @@ websearch_to_tsquery('english', 'pipeline board filter')",
        (v,),
    ).fetchall()
    assert ("deals-board-view#filter-the-board:0",) in hits
    assert set(one(conn, "SELECT array_agg(module) FROM module_catalogue")) == set(
        CATALOGUE.modules
    )
    recipe = one(conn, "SELECT recipe FROM index_versions WHERE index_version = %s", v)
    assert recipe["embed_model"] == "fake-model@1" and recipe["chunker_config_hash"]


def test_modules_are_gin_indexed_and_vector_search_stays_exact(
    conn: psycopg.Connection[Any],
) -> None:
    indexes = conn.execute("SELECT indexdef FROM pg_indexes WHERE tablename = 'chunks'").fetchall()
    defs = " ".join(d for (d,) in indexes).lower()
    assert "gin (modules)" in defs
    assert "hnsw" not in defs and "ivfflat" not in defs, "exact search only (CLAUDE.md)"
