"""S2.2.2: done when candidates are reranked by bge-reranker-v2-m3 and a score threshold
is configurable. Unit tests use a fake scorer; the `model` test needs the real tokenizer."""

import dataclasses
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from chatbot.models_config import RerankerConfig, load_models_config
from chatbot.ports.retriever import Candidate
from chatbot.retrieval.rerank import CrossEncoderReranker, passage, sigmoid

ROOT = Path(__file__).parents[2]
CONFIG = RerankerConfig(model_id="fake/reranker", revision="0" * 40, max_length=512, threshold=0.5)


def cand(name: str, fused_rank: int) -> Candidate:
    return Candidate(
        chunk_id=f"doc#{name}:0",
        doc_id="doc",
        anchor=name,
        breadcrumb=f"Doc > {name}",
        content=f"text about {name}",
        content_hash=f"hash-{name}",
        modules=("core",),
        index_version=7,
        vec_rank=fused_rank,
        kw_rank=None,
        score=1 / (60 + fused_rank),
    )


def reranker(
    logits: dict[str, float], seen: list[tuple[str, str]] | None = None
) -> CrossEncoderReranker:
    def score(pairs: list[tuple[str, str]]) -> list[float]:
        if seen is not None:
            seen.extend(pairs)
        return [logits[p.split("text about ")[1]] for _, p in pairs]

    return CrossEncoderReranker(CONFIG, score_pairs=score)


CANDS = [cand("a", 1), cand("b", 2), cand("c", 3), cand("d", 4)]


async def test_candidates_come_back_best_first_with_sigmoid_scores() -> None:
    got = await reranker({"a": -2.0, "b": 3.0, "c": 0.0, "d": 1.0}).rerank("q", CANDS, 4)
    assert [c.anchor for c in got] == ["b", "d", "c", "a"]
    assert got[0].rerank_score == pytest.approx(1 / (1 + math.exp(-3.0)))
    assert got[2].rerank_score == pytest.approx(0.5)


async def test_k_caps_the_results() -> None:
    got = await reranker({"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0}).rerank("q", CANDS, 2)
    assert [c.anchor for c in got] == ["d", "c"]


async def test_equal_scores_keep_the_fused_order() -> None:
    got = await reranker({"a": 0.0, "b": 1.0, "c": 0.0, "d": 1.0}).rerank("q", CANDS, 4)
    assert [c.anchor for c in got] == ["b", "d", "a", "c"]


async def test_reranking_only_reorders_and_cuts_never_adds_or_edits() -> None:
    """Permission filtering happened in SQL; the reranker must not be able to widen it."""
    got = await reranker({"a": 4.0, "b": 3.0, "c": 2.0, "d": 1.0}).rerank("q", CANDS, 3)
    originals = {c.chunk_id: c for c in CANDS}
    for c in got:
        assert dataclasses.replace(c, rerank_score=None) == originals[c.chunk_id]


async def test_the_model_reads_the_query_with_the_breadcrumb_and_content() -> None:
    seen: list[tuple[str, str]] = []
    await reranker({"a": 0.0}, seen).rerank("move a deal", [CANDS[0]], 1)
    assert seen == [("move a deal", "Doc > a\n\ntext about a")]
    assert passage(CANDS[0]) == "Doc > a\n\ntext about a"


async def test_no_candidates_means_no_model_call() -> None:
    seen: list[tuple[str, str]] = []
    assert await reranker({}, seen).rerank("q", [], 5) == []
    assert seen == []


async def test_a_scorer_that_loses_candidates_is_an_error() -> None:
    r = CrossEncoderReranker(CONFIG, score_pairs=lambda pairs: [0.0])
    with pytest.raises(ValueError, match="1 scores for 4 candidates"):
        await r.rerank("q", CANDS, 4)


async def test_k_must_be_positive() -> None:
    with pytest.raises(ValueError, match="k"):
        await reranker({}).rerank("q", CANDS, 0)


def test_sigmoid_is_stable_for_extreme_logits() -> None:
    assert sigmoid(1000.0) == 1.0 and sigmoid(-1000.0) == 0.0 and sigmoid(0.0) == 0.5


# --- config ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"revision": "main"}, "revision"),
        ({"threshold": 1.5}, "threshold"),
        ({"threshold": -0.1}, "threshold"),
        ({"max_length": 0}, "max_length"),
        ({"dtype": "bfloat16"}, "dtype"),
    ],
)
def test_bad_reranker_config_is_rejected(change: dict[str, object], reason: str) -> None:
    base = CONFIG.model_dump()
    with pytest.raises(ValidationError, match=reason):
        RerankerConfig.model_validate(base | change)


def test_the_repo_config_pins_the_reranker() -> None:
    config = load_models_config(ROOT / "config" / "models.yaml").reranker
    assert config is not None
    assert config.model_id == "BAAI/bge-reranker-v2-m3"
    assert config.key == "BAAI/bge-reranker-v2-m3@953dc6f6f85a"
    assert 0 < config.threshold < 1 and config.dtype == "float16"


# --- the real tokenizer (needs the model downloaded) ----------------------------------------


@pytest.mark.model
def test_every_corpus_chunk_and_a_question_fit_in_max_length() -> None:
    """Truncation would silently cut the end of a procedure out of the relevance score."""
    from transformers import AutoTokenizer

    from chatbot.adapters.local_catalogue import load_catalogue
    from chatbot.ingest.chunker import Chunker
    from chatbot.ingest.validate import DocValidator, load_frontmatter_schema

    config = load_models_config(ROOT / "config" / "models.yaml").reranker
    assert config is not None
    tok = AutoTokenizer.from_pretrained(config.model_id, revision=config.revision)
    known = frozenset(load_catalogue(ROOT / "data" / "module_catalogue.yaml").modules)
    docs = DocValidator(
        known, load_frontmatter_schema(ROOT / "data" / "spec" / "doc_frontmatter.schema.json")
    ).read_corpus(ROOT / "data" / "docs")
    question = "how do i get an email sent automatically when a deal moves to the negotiation stage"
    longest = max(
        len(tok(question, c.embed_text)["input_ids"])
        for d in docs
        for c in Chunker(lambda t: len(t.split())).chunk(d)
    )
    assert longest <= config.max_length, f"longest pair is {longest} tokens"
