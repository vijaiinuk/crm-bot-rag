"""S2.3.1: the rerank score cache. A counting fake scorer shows exactly which
(query, chunk) pairs reached the model."""

from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from typing import ClassVar

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

from chatbot.models_config import RerankerConfig
from chatbot.ports.retriever import Candidate
from chatbot.retrieval.rerank import CrossEncoderReranker
from chatbot.retrieval.rerank_cache import CachingReranker

pytestmark = pytest.mark.db


def config(model_id: str = "fake/reranker") -> RerankerConfig:
    return RerankerConfig(model_id=model_id, revision="0" * 40, max_length=512, threshold=0.3)


def cand(name: str, content: str | None = None) -> Candidate:
    content = content or f"text about {name}"
    return Candidate(
        chunk_id=f"doc#{name}:0",
        doc_id="doc",
        anchor=name,
        breadcrumb=f"Doc > {name}",
        content=content,
        content_hash=f"hash-of-{content}",
        modules=("core",),
        index_version=1,
        vec_rank=1,
        kw_rank=None,
        score=0.01,
    )


class CountingScorer:
    LOGITS: ClassVar[dict[str, float]] = {"a": 2.0, "b": -1.0, "c": 0.5}

    def __init__(self) -> None:
        self.scored: list[tuple[str, str]] = []

    def __call__(self, pairs: list[tuple[str, str]]) -> list[float]:
        self.scored += pairs
        return [self.LOGITS.get(p.rsplit(" ", 1)[-1], 0.0) for _, p in pairs]


@pytest.fixture
def clean(pg_url: str) -> Iterator[None]:
    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute("TRUNCATE rerank_cache")
    yield


@pytest.fixture
async def pool(pg_url: str, clean: None) -> AsyncIterator[AsyncConnectionPool]:
    async with AsyncConnectionPool(pg_url, min_size=1, max_size=2) as p:
        yield p


def caching(
    pool: AsyncConnectionPool, scorer: CountingScorer, model: str = "fake/reranker"
) -> CachingReranker:
    return CachingReranker(CrossEncoderReranker(config(model), score_pairs=scorer), pool)


CANDS = [cand("a"), cand("b"), cand("c")]


async def test_a_second_run_rescores_nothing_and_ranks_the_same(pool: AsyncConnectionPool) -> None:
    scorer = CountingScorer()
    r = caching(pool, scorer)
    first = await r.rerank("move a deal", CANDS, 3)
    assert len(scorer.scored) == 3
    second = await r.rerank("move a deal", CANDS, 3)
    assert len(scorer.scored) == 3, "every score came from the cache"
    assert [(c.chunk_id, c.rerank_score) for c in second] == [
        (c.chunk_id, c.rerank_score) for c in first
    ]
    assert [c.anchor for c in first] == ["a", "c", "b"]


async def test_cached_results_match_the_uncached_reranker(pool: AsyncConnectionPool) -> None:
    plain = await CrossEncoderReranker(config(), score_pairs=CountingScorer()).rerank("q", CANDS, 2)
    r = caching(pool, CountingScorer())
    await r.rerank("q", CANDS, 3)  # fill the cache
    cached = await r.rerank("q", CANDS, 2)
    assert [c.chunk_id for c in cached] == [c.chunk_id for c in plain]
    for got, want in zip(cached, plain, strict=True):
        assert got.rerank_score == pytest.approx(want.rerank_score)


async def test_a_changed_chunk_is_rescored_and_the_rest_reused(pool: AsyncConnectionPool) -> None:
    scorer = CountingScorer()
    r = caching(pool, scorer)
    await r.rerank("q", CANDS, 3)
    edited = [CANDS[0], cand("b", "new wording about c"), CANDS[2]]
    await r.rerank("q", edited, 3)
    assert len(scorer.scored) == 4
    assert scorer.scored[-1] == ("q", "Doc > b\n\nnew wording about c")


async def test_a_different_query_or_model_never_reuses_scores(pool: AsyncConnectionPool) -> None:
    scorer = CountingScorer()
    await caching(pool, scorer).rerank("q", CANDS, 3)
    await caching(pool, scorer).rerank("another question", CANDS, 3)
    await caching(pool, scorer, model="other/reranker").rerank("q", CANDS, 3)
    assert len(scorer.scored) == 9


async def test_a_partly_cached_request_scores_only_the_missing_chunks(
    pool: AsyncConnectionPool,
) -> None:
    scorer = CountingScorer()
    r = caching(pool, scorer)
    await r.rerank("q", CANDS[:1], 1)
    got = await r.rerank("q", CANDS, 3)
    assert [p for _, p in scorer.scored] == [
        "Doc > a\n\ntext about a",
        "Doc > b\n\ntext about b",
        "Doc > c\n\ntext about c",
    ]
    assert len(got) == 3


async def test_the_key_is_the_inner_rerankers(pool: AsyncConnectionPool) -> None:
    assert caching(pool, CountingScorer()).key == "fake/reranker@000000000000"


async def test_a_candidate_without_a_content_hash_is_refused(pool: AsyncConnectionPool) -> None:
    """An empty hash would share one cache entry across chunks: wrong scores, silently."""
    unhashed = replace(cand("x"), content_hash="")
    with pytest.raises(ValueError, match="content_hash"):
        await caching(pool, CountingScorer()).rerank("q", [CANDS[0], unhashed], 2)
