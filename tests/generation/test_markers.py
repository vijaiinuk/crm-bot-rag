"""S3.1.3b: citation markers stripped from a token stream, wherever the tokens split."""

import pytest

from chatbot.generation.markers import MarkerStream
from chatbot.generation.prompt import NOT_FOUND


def run(*deltas: str) -> tuple[str, MarkerStream]:
    ms = MarkerStream()
    out = "".join(ms.feed(d) for d in deltas) + ms.finish()
    return out, ms


def test_markers_are_removed_with_the_space_before_them() -> None:
    out, ms = run("Open **Deals** [1]. Then drag the card [2][3].")
    assert out == "Open **Deals**. Then drag the card."
    assert ms.cited == [1, 2, 3]


@pytest.mark.parametrize(
    "deltas",
    [
        ("Open it [", "1", "]."),
        ("Open it [1", "]."),
        ("Open it ", "[1]", "."),
        (
            "Open it",
            " [1].",
        ),
        tuple("Open it [1]."),  # one character at a time
    ],
)
def test_a_marker_split_across_tokens_is_still_removed(deltas: tuple[str, ...]) -> None:
    out, ms = run(*deltas)
    assert out == "Open it." and ms.cited == [1]


def test_comma_lists_are_one_marker_and_repeats_are_cited_once() -> None:
    out, ms = run("A [1, 3]. B [3]. C [2].")
    assert out == "A. B. C." and ms.cited == [1, 3, 2]


def test_brackets_that_are_not_markers_pass_through() -> None:
    out, ms = run("Select [Save] or type [2026] in **Year**.")
    assert out == "Select [Save] or type [2026] in **Year**."
    assert ms.cited == []


def test_text_streams_without_waiting_for_the_end() -> None:
    ms = MarkerStream()
    assert ms.feed("Go to **Deals** and ") == "Go to **Deals** and"  # trailing space held
    assert ms.feed("open it [") == " open it"  # "[" might start a marker
    assert ms.feed("1].") == "."


def test_the_sentinel_never_leaks_a_token() -> None:
    ms = MarkerStream()
    streamed = [ms.feed(d) for d in ("[[NOT", "_FOU", "ND]]")] + [ms.finish()]
    assert streamed == ["", "", "", ""] and ms.not_found


def test_text_that_only_starts_like_the_sentinel_is_released() -> None:
    out, ms = run("[[", "Note]] see below")
    assert not ms.not_found and out == "[[Note]] see below"


def test_a_normal_answer_is_released_as_soon_as_it_cannot_be_the_sentinel() -> None:
    ms = MarkerStream()
    assert ms.feed("To") == "To"
    assert not ms.not_found


def test_the_sentinel_with_surrounding_whitespace_counts() -> None:
    _, ms = run("  ", NOT_FOUND, "\n")
    assert ms.not_found
