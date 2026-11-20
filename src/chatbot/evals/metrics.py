"""Retrieval metrics (S2.3.1). Pure functions. Design: docs/backlog.md, "S2.3.1 design".

A ranking is one entry per retrieved chunk, best first: the set of `doc_id#anchor`
labels that chunk satisfies (its own section and every ancestor section). k counts
chunks, because the generator's context holds a fixed number of chunks.
"""

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

Ranking = Sequence[frozenset[str]]
DEPTH = 20  # MRR looks this far down; a first match beyond it scores 0
KS = (1, 3, 5, 10)


@dataclass(frozen=True, slots=True)
class PairResult:
    question_id: str
    persona: str
    category: str
    required: tuple[str, ...]
    ranking: tuple[frozenset[str], ...]


@dataclass(frozen=True, slots=True)
class Summary:
    n: int
    recall: dict[int, float]
    complete: dict[int, float]
    mrr: float


@dataclass(frozen=True, slots=True)
class GateCounts:
    n: int
    above: int  # pairs whose top rerank score is at or above the threshold


def _require(required: Sequence[str], k: int | None = None) -> frozenset[str]:
    if not required:
        raise ValueError("no required labels: an answer pair needs at least one to be scored")
    if k is not None and k < 1:
        raise ValueError(f"k must be at least 1, got {k}")
    return frozenset(required)


def _found(ranking: Ranking, k: int) -> frozenset[str]:
    return frozenset().union(*ranking[:k])


def recall_at(required: Sequence[str], ranking: Ranking, k: int) -> float:
    """Share of required labels satisfied by the top k chunks."""
    req = _require(required, k)
    return len(req & _found(ranking, k)) / len(req)


def complete_at(required: Sequence[str], ranking: Ranking, k: int) -> bool:
    """Every required label satisfied by the top k chunks."""
    return _require(required, k) <= _found(ranking, k)


def reciprocal_rank(required: Sequence[str], ranking: Ranking, depth: int = DEPTH) -> float:
    """1 / chunk rank of the first chunk satisfying any required label; 0 beyond depth."""
    req = _require(required)
    for rank, labels in enumerate(ranking[:depth], start=1):
        if labels & req:
            return 1.0 / rank
    return 0.0


def _summary(results: Sequence[PairResult], ks: Sequence[int], depth: int) -> Summary:
    return Summary(
        n=len(results),
        recall={
            k: statistics.fmean(recall_at(r.required, r.ranking, k) for r in results) for k in ks
        },
        complete={
            k: statistics.fmean(float(complete_at(r.required, r.ranking, k)) for r in results)
            for k in ks
        },
        mrr=statistics.fmean(reciprocal_rank(r.required, r.ranking, depth) for r in results),
    )


def summarize(
    results: Sequence[PairResult], ks: Sequence[int] = KS, depth: int = DEPTH
) -> dict[str, Summary]:
    """Per category (in order of first appearance), then "overall"."""
    if not results:
        raise ValueError("no results to summarize")
    by_category: dict[str, list[PairResult]] = {}
    for r in results:
        by_category.setdefault(r.category, []).append(r)
    out = {cat: _summary(rs, ks, depth) for cat, rs in by_category.items()}
    out["overall"] = _summary(results, ks, depth)
    return out


_GROUP = {
    "answer": "answer",
    "restricted": "restricted",
    "not_found": "nothing",
    "out_of_scope": "nothing",
}


def gate_counts(
    outcomes: Sequence[tuple[str, float | None]], threshold: float
) -> dict[str, GateCounts]:
    """(expected outcome, top rerank score or None) -> counts for "answer", "restricted"
    and "nothing" (not_found + out_of_scope). No candidates (None) counts as below."""
    n = {"answer": 0, "restricted": 0, "nothing": 0}
    above = dict.fromkeys(n, 0)
    for outcome, score in outcomes:
        if outcome not in _GROUP:
            raise ValueError(f"unknown expected outcome {outcome!r}")
        group = _GROUP[outcome]
        n[group] += 1
        above[group] += score is not None and score >= threshold
    return {g: GateCounts(n=n[g], above=above[g]) for g in n}
