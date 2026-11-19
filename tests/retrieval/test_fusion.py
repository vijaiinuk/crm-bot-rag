"""S2.2.1: reciprocal rank fusion. Pure function, hand-computed expectations."""

import pytest

from chatbot.retrieval.fusion import Fused, rrf


def ids(fused: list[Fused]) -> list[str]:
    return [f.chunk_id for f in fused]


def test_scores_are_the_sum_of_one_over_k_plus_rank() -> None:
    fused = rrf({"vec": ["a", "b", "c"], "kw": ["c", "a"]})
    scores = {f.chunk_id: f.score for f in fused}
    assert scores["a"] == pytest.approx(1 / 61 + 1 / 62)  # 0.032522
    assert scores["c"] == pytest.approx(1 / 63 + 1 / 61)  # 0.032266
    assert scores["b"] == pytest.approx(1 / 62)  # 0.016129
    assert ids(fused) == ["a", "c", "b"]


def test_each_result_reports_its_rank_in_every_list_it_appears_in() -> None:
    by_id = {f.chunk_id: f for f in rrf({"vec": ["a", "b", "c"], "kw": ["c", "a"]})}
    assert by_id["a"].ranks == {"vec": 1, "kw": 2}
    assert by_id["b"].ranks == {"vec": 2}
    assert by_id["c"].ranks == {"vec": 3, "kw": 1}


def test_agreement_between_lists_beats_one_lists_top_result() -> None:
    """The point of k = 60: second in both lists outranks first in only one."""
    assert ids(rrf({"vec": ["x", "y"], "kw": ["y"]}))[0] == "y"
    assert ids(rrf({"vec": ["x", "y"], "kw": ["z", "y"]}))[0] == "y"


def test_with_k_zero_one_top_result_equals_two_second_places() -> None:
    """k = 0 makes scores plain 1/rank: first in one list (1.0) ties with second in both
    (0.5 + 0.5). Compare k = 60 above, where agreement wins. The tie goes to the better
    single rank."""
    fused = rrf({"vec": ["x", "y"], "kw": ["z", "y"]}, k=0)
    assert {f.chunk_id: f.score for f in fused} == {"x": 1.0, "y": 1.0, "z": 1.0}
    assert ids(fused) == ["x", "z", "y"]  # x and z were ranked 1; y's best was 2


def test_mirror_ties_go_to_the_earlier_list() -> None:
    """(1, 2) and (2, 1) tie on score and on best rank; the first list passed decides.
    The retriever passes vector first, as the stronger list (S2.2.1 design)."""
    assert ids(rrf({"vec": ["b", "a"], "kw": ["a", "b"]})) == ["b", "a"]
    assert ids(rrf({"vec": ["q"], "kw": ["p"]})) == ["q", "p"]
    assert ids(rrf({"kw": ["p"], "vec": ["q"]})) == ["p", "q"], "order of lists, not names"


def test_a_single_list_keeps_its_order() -> None:
    assert ids(rrf({"vec": ["c", "a", "b"]})) == ["c", "a", "b"]


def test_empty_input_gives_nothing() -> None:
    assert rrf({}) == []
    assert rrf({"vec": [], "kw": []}) == []


def test_a_list_that_repeats_a_chunk_is_a_bug() -> None:
    with pytest.raises(ValueError, match=r"'a'.*twice"):
        rrf({"vec": ["a", "b", "a"]})


def test_k_must_not_be_negative() -> None:
    with pytest.raises(ValueError, match="k"):
        rrf({"vec": ["a"]}, k=-1)
