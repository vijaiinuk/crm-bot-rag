"""Pure release logic: who can see what after a publish, and what the gate decides."""

import pytest

from chatbot.admin.models import ModuleChange
from chatbot.admin.releases import (
    GateCheck,
    anchors_of,
    gate_outcome,
    module_diff,
    orphaned_labels,
    slugify,
)


def change(diff: list[ModuleChange], doc_id: str) -> ModuleChange:
    (c,) = [c for c in diff if c.doc_id == doc_id]
    return c


# --- module_diff ---------------------------------------------------------------


def test_dropping_a_module_widens_access() -> None:
    """[deals, reports] -> [reports]: users without deals can now see it."""
    c = change(module_diff({"d": ["deals", "reports"]}, {"d": ["reports"]}), "d")
    assert c.change == "widened"
    assert c.dropped == ["deals"]


def test_moving_to_core_widens_access() -> None:
    assert change(module_diff({"d": ["deals"]}, {"d": ["core"]}), "d").change == "widened"


def test_replacing_a_module_counts_as_widened() -> None:
    """[deals] -> [campaigns]: campaigns-only users gain access, so it needs a human."""
    c = change(module_diff({"d": ["deals"]}, {"d": ["campaigns"]}), "d")
    assert c.change == "widened"
    assert (c.dropped, c.added) == (["deals"], ["campaigns"])


def test_adding_a_module_narrows_access() -> None:
    c = change(module_diff({"d": ["deals"]}, {"d": ["deals", "campaigns"]}), "d")
    assert c.change == "narrowed"
    assert c.added == ["campaigns"]


def test_same_modules_in_any_order_is_unchanged() -> None:
    assert change(module_diff({"d": ["a", "b"]}, {"d": ["b", "a"]}), "d").change == "unchanged"


def test_new_and_retired_docs() -> None:
    diff = module_diff({"old": ["deals"]}, {"new": ["core"]})
    assert change(diff, "new").change == "new"
    assert change(diff, "old").change == "retired"


def test_diff_is_sorted_by_doc_id() -> None:
    diff = module_diff({"b": ["x"], "a": ["x"]}, {"b": ["x"], "a": ["x"]})
    assert [c.doc_id for c in diff] == ["a", "b"]


# --- anchors and orphaned labels -------------------------------------------------


@pytest.mark.parametrize(
    ("heading", "slug"),
    [
        ("Triggers", "triggers"),
        ("Stage triggers & actions", "stage-triggers-actions"),
        ("  Set up (step 2)  ", "set-up-step-2"),
        ("Déjà vu", "deja-vu"),
    ],
)
def test_slugify(heading: str, slug: str) -> None:
    assert slugify(heading) == slug


def test_anchors_of_reads_headings_not_code() -> None:
    md = "# Title\n\nText\n\n## Triggers\n\n```\n# not a heading\n```\n\n### Add an action\n"
    assert anchors_of(md) == ["title", "triggers", "add-an-action"]


def test_orphaned_labels_finds_missing_anchor_and_missing_doc() -> None:
    anchors = {"deals-stage-automation": {"stage-triggers"}, "contacts-import": {"csv"}}
    questions = [
        ("q1", ["deals-stage-automation#triggers", "contacts-import#csv"]),
        ("q2", ["contacts-import#csv"]),
        ("q3", ["retired-doc#intro"]),
    ]
    found = orphaned_labels(questions, anchors)
    assert [(o.question_id, o.label) for o in found] == [
        ("q1", "deals-stage-automation#triggers"),
        ("q3", "retired-doc#intro"),
    ]


# --- gate outcome ----------------------------------------------------------------


def test_gate_outcome_precedence() -> None:
    ok = GateCheck(name="a", status="pass", detail="")
    confirm = GateCheck(name="b", status="needs_confirmation", detail="")
    fail = GateCheck(name="c", status="fail", detail="")
    assert gate_outcome([ok, ok]) == "live"
    assert gate_outcome([ok, confirm]) == "awaiting_confirmation"
    assert gate_outcome([confirm, fail]) == "failed", "a failure always wins"
