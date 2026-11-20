"""S2.3.1: retrieval metrics. Pure functions, hand-computed expectations.

A ranking is one entry per retrieved chunk, best first: the labels that chunk satisfies.
"""

import pytest

from chatbot.evals.metrics import (
    GateCounts,
    PairResult,
    complete_at,
    gate_counts,
    recall_at,
    reciprocal_rank,
    summarize,
)


def ranking(*chunks: str | tuple[str, ...]) -> tuple[frozenset[str], ...]:
    """ranking("x", "a", ("sub", "parent")) -> one entry per chunk."""
    return tuple(frozenset((c,) if isinstance(c, str) else c) for c in chunks)


# Required {A, B}. Chunk ranks: 1 X, 2 A (part 0), 3 A (part 1), 4 Y, 5 B.
R = ("A", "B")
RANKING = ranking("X", "A", "A", "Y", "B")


# --- recall@k and complete recall@k ---------------------------------------------------------


@pytest.mark.parametrize(
    ("k", "recall", "complete"),
    [
        (1, 0.0, False),  # X only
        (2, 0.5, False),  # A found
        (3, 0.5, False),  # A's second part adds nothing
        (4, 0.5, False),  # k counts chunks: 4 chunks, still only A
        (5, 1.0, True),  # B at chunk 5
        (10, 1.0, True),  # k beyond the ranking is fine
    ],
)
def test_recall_and_complete_recall_count_chunks(k: int, recall: float, complete: bool) -> None:
    assert recall_at(R, RANKING, k) == recall
    assert complete_at(R, RANKING, k) is complete


def test_a_subsection_chunk_satisfies_its_parent_label() -> None:
    """An empty `##` has no chunk; its `###` children stand in for it."""
    r = ranking("X", ("d#sub", "d#parent"))
    assert recall_at(["d#parent"], r, 2) == 1.0
    assert complete_at(["d#parent", "d#sub"], r, 2)


def test_single_label_recall_is_all_or_nothing() -> None:
    assert recall_at(["A"], RANKING, 1) == 0.0
    assert recall_at(["A"], RANKING, 2) == 1.0


def test_three_labels_give_thirds() -> None:
    assert recall_at(["A", "B", "C"], RANKING, 5) == pytest.approx(2 / 3)
    assert not complete_at(["A", "B", "C"], RANKING, 10)


def test_an_empty_ranking_finds_nothing() -> None:
    assert recall_at(R, (), 5) == 0.0
    assert not complete_at(R, (), 5)
    assert reciprocal_rank(R, ()) == 0.0


# --- reciprocal rank ------------------------------------------------------------------------


def test_reciprocal_rank_is_one_over_the_first_matching_chunk() -> None:
    assert reciprocal_rank(R, RANKING) == 0.5  # A at chunk 2
    assert reciprocal_rank(["B"], RANKING) == 0.2  # B at chunk 5
    assert reciprocal_rank(["Y", "B"], RANKING) == 0.25  # whichever comes first: Y at 4


def test_reciprocal_rank_is_zero_when_nothing_matches_within_depth() -> None:
    assert reciprocal_rank(["Z"], RANKING) == 0.0
    deep = ranking(*["X"] * 20, "A")  # A at chunk 21
    assert reciprocal_rank(["A"], deep, depth=20) == 0.0
    assert reciprocal_rank(["A"], deep, depth=21) == pytest.approx(1 / 21)


# --- bad input is a bug, not a zero ---------------------------------------------------------


def test_no_required_labels_is_an_error() -> None:
    """An `answer` pair with no labels can't be scored; 0 or 1 would both be lies."""
    for metric in (recall_at, complete_at):
        with pytest.raises(ValueError, match="required"):
            metric([], RANKING, 5)
    with pytest.raises(ValueError, match="required"):
        reciprocal_rank([], RANKING)


def test_k_must_be_positive() -> None:
    with pytest.raises(ValueError, match="k"):
        recall_at(R, RANKING, 0)


# --- aggregation ----------------------------------------------------------------------------


def pair(
    qid: str, category: str, required: tuple[str, ...], r: tuple[frozenset[str], ...]
) -> PairResult:
    return PairResult(qid, "p@acme", category, required, r)


def test_summaries_average_per_category_and_overall() -> None:
    results = [
        pair("q-1", "single", ("A",), ranking("A")),  # recall@1 1, complete@1 1, RR 1
        pair("q-2", "single", ("A",), ranking("X", "A")),  # recall@1 0, @3 1, RR 0.5
        pair("q-3", "multi_hop", ("A", "B"), ranking("A", "X", "B")),  # @1 0.5/F, @3 1/T, RR 1
    ]
    s = summarize(results, ks=(1, 3))
    assert list(s) == ["single", "multi_hop", "overall"]

    assert s["single"].n == 2
    assert s["single"].recall == {1: 0.5, 3: 1.0}
    assert s["single"].complete == {1: 0.5, 3: 1.0}
    assert s["single"].mrr == pytest.approx(0.75)

    assert s["multi_hop"].n == 1
    assert s["multi_hop"].recall == {1: 0.5, 3: 1.0}
    assert s["multi_hop"].complete == {1: 0.0, 3: 1.0}

    o = s["overall"]
    assert o.n == 3
    assert o.recall[1] == pytest.approx((1 + 0 + 0.5) / 3)
    assert o.complete[1] == pytest.approx(1 / 3)
    assert o.mrr == pytest.approx((1 + 0.5 + 1) / 3)


def test_summarizing_nothing_is_an_error() -> None:
    with pytest.raises(ValueError, match="no results"):
        summarize([])


# --- the threshold check --------------------------------------------------------------------


def test_gate_counts_group_outcomes_and_treat_no_candidates_as_below() -> None:
    counts = gate_counts(
        [
            ("answer", 0.9),
            ("answer", 0.3),  # at the threshold counts as above
            ("answer", 0.1),
            ("answer", None),  # no candidates at all
            ("restricted", 0.6),
            ("restricted", 0.01),
            ("not_found", 0.5),
            ("out_of_scope", 0.0),
        ],
        threshold=0.3,
    )
    assert counts == {
        "answer": GateCounts(n=4, above=2),
        "restricted": GateCounts(n=2, above=1),
        "nothing": GateCounts(n=2, above=1),
    }


def test_an_unknown_outcome_is_an_error() -> None:
    with pytest.raises(ValueError, match="maybe"):
        gate_counts([("maybe", 0.5)], threshold=0.3)
