"""S2.3.1: resolving `doc_id#anchor` labels to chunks of one index version."""

import pytest

from chatbot.evals.labels import ChunkRow, OrphanLabels, check_labels, label_index

ROWS = [
    ChunkRow("d#a:0", "d", "a", None),
    ChunkRow("d#a:1", "d", "a", None),  # a split section: two parts
    ChunkRow("d#sub:0", "d", "sub", "parent"),  # `## parent` has no text, so no chunk
    ChunkRow("e#a:0", "e", "a", None),  # same anchor, different doc
]


def test_each_part_of_a_section_satisfies_its_label() -> None:
    idx = label_index(ROWS)
    assert idx["d#a:0"] == idx["d#a:1"] == frozenset({"d#a"})
    assert idx["e#a:0"] == frozenset({"e#a"}), "anchors are per doc"


def test_a_subsection_satisfies_its_own_and_its_parents_label() -> None:
    assert label_index(ROWS)["d#sub:0"] == frozenset({"d#sub", "d#parent"})


def test_every_ancestor_counts_not_just_the_parent() -> None:
    rows = [
        ChunkRow("d#mid:0", "d", "mid", "top"),  # ### under an empty ##
        ChunkRow("d#leaf:0", "d", "leaf", "mid"),  # #### under the ###
    ]
    assert label_index(rows)["d#leaf:0"] == frozenset({"d#leaf", "d#mid", "d#top"})


def test_labels_that_resolve_pass() -> None:
    check_labels(["d#a", "d#parent", "d#sub", "e#a"], label_index(ROWS))


def test_orphan_labels_abort_listing_each_once_sorted() -> None:
    with pytest.raises(OrphanLabels) as exc:
        check_labels(["d#gone", "d#a", "x#a", "d#gone"], label_index(ROWS))
    assert exc.value.labels == ["d#gone", "x#a"]
    assert "2 eval label(s)" in str(exc.value)
