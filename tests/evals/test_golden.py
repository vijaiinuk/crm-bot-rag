"""S1.3.1: expected outcomes are derived from labels and modules, never guessed.

These tests define the ground truth that the permission suite, refusal
accuracy and every retrieval metric trust. Written before the implementation.
"""

import pytest
from pydantic import ValidationError

from chatbot.evals.golden import (
    Expected,
    GoldenError,
    GoldenQuestion,
    derive_expected,
    expected_for,
)

# A tiny corpus: doc_id -> the modules a reader needs (all of them, rule 5).
DOCS = {
    "deals-stage-automation": frozenset({"deals"}),
    "campaigns-triggered-emails": frozenset({"campaigns"}),
    "campaigns-deal-triggers": frozenset({"campaigns", "deals"}),  # workflow guide
    "deals-forecasting": frozenset({"deals", "reports"}),
    "core-navigation": frozenset({"core"}),
}
MANAGER = frozenset({"core", "contacts", "deals", "campaigns", "reports"})  # sales_manager@acme
REP = frozenset({"core", "contacts", "deals"})  # sales_rep@globex
MARKETER = frozenset({"core", "contacts", "campaigns"})  # marketing_manager@globex
CORE_ONLY = frozenset({"core"})


# --- answer -------------------------------------------------------------------------------


def test_persona_holding_the_docs_modules_gets_an_answer() -> None:
    got = derive_expected(["deals-stage-automation#triggers"], REP, DOCS)
    assert got == Expected(outcome="answer", required=["deals-stage-automation#triggers"])


def test_core_docs_are_answered_for_everyone() -> None:
    assert derive_expected(["core-navigation#search"], CORE_ONLY, DOCS).outcome == "answer"


def test_several_sections_of_one_doc_need_only_that_docs_modules() -> None:
    labels = ["deals-stage-automation#triggers", "deals-stage-automation#actions"]
    assert derive_expected(labels, REP, DOCS).outcome == "answer"


# --- restricted ---------------------------------------------------------------------------


def test_persona_missing_the_module_is_restricted_with_exactly_that_module() -> None:
    got = derive_expected(["campaigns-triggered-emails#setup"], REP, DOCS)
    assert got == Expected(
        outcome="restricted",
        required=["campaigns-triggered-emails#setup"],
        missing_modules=["campaigns"],
    )


def test_a_two_module_doc_needs_both_modules() -> None:
    """Rule 5: a doc tagged [campaigns, deals] is visible only with both."""
    label = ["campaigns-deal-triggers#connect-a-stage-to-a-campaign"]
    assert derive_expected(label, MANAGER, DOCS).outcome == "answer"
    assert derive_expected(label, REP, DOCS).missing_modules == ["campaigns"]
    assert derive_expected(label, MARKETER, DOCS).missing_modules == ["deals"]


def test_multi_hop_needs_every_docs_modules() -> None:
    """Holding one of two needed docs is not enough: there's no partial answer outcome."""
    labels = ["deals-stage-automation#triggers", "campaigns-triggered-emails#setup"]
    got = derive_expected(labels, REP, DOCS)
    assert got.outcome == "restricted" and got.missing_modules == ["campaigns"]


def test_missing_modules_are_sorted_and_unique() -> None:
    labels = ["deals-forecasting#forecast-reports", "campaigns-deal-triggers#choose-recipients"]
    got = derive_expected(labels, CORE_ONLY, DOCS)
    assert got.missing_modules == ["campaigns", "deals", "reports"]


def test_required_labels_are_kept_as_given_for_restricted_personas() -> None:
    """Retrieval evals still need to know what *would* answer it."""
    labels = ["campaigns-triggered-emails#setup"]
    assert derive_expected(labels, REP, DOCS).required == labels


# --- fail closed --------------------------------------------------------------------------


def test_unknown_doc_is_an_error_not_an_answer() -> None:
    with pytest.raises(GoldenError, match="no-such-doc"):
        derive_expected(["no-such-doc#intro"], MANAGER, DOCS)


@pytest.mark.parametrize(
    "label", ["deals-stage-automation", "#triggers", "deals-stage-automation#"]
)
def test_malformed_label_is_an_error(label: str) -> None:
    with pytest.raises(GoldenError, match="doc_id#anchor"):
        derive_expected([label], MANAGER, DOCS)


def test_no_labels_is_an_error() -> None:
    """Without labels there is nothing to derive from; never default to answer."""
    with pytest.raises(GoldenError, match="no required labels"):
        derive_expected([], MANAGER, DOCS)


# --- by category --------------------------------------------------------------------------


@pytest.mark.parametrize("category", ["single", "multi_hop", "restricted", "adversarial"])
def test_labelled_categories_are_derived(category: str) -> None:
    got = expected_for(category, ["campaigns-triggered-emails#setup"], REP, DOCS)  # type: ignore[arg-type]
    assert got.outcome == "restricted" and got.missing_modules == ["campaigns"]


def test_unanswerable_is_not_found_and_has_no_labels() -> None:
    assert expected_for("unanswerable", [], MANAGER, DOCS) == Expected(outcome="not_found")


def test_out_of_scope_is_out_of_scope_for_everyone() -> None:
    assert expected_for("out_of_scope", [], CORE_ONLY, DOCS) == Expected(outcome="out_of_scope")


@pytest.mark.parametrize("category", ["unanswerable", "out_of_scope"])
def test_unlabelled_categories_reject_labels(category: str) -> None:
    with pytest.raises(GoldenError, match="takes no labels"):
        expected_for(category, ["deals-stage-automation#triggers"], MANAGER, DOCS)  # type: ignore[arg-type]


# --- the YAML contract --------------------------------------------------------------------


def test_contract_example_parses() -> None:
    q = GoldenQuestion.model_validate(
        {
            "id": "q-0042",
            "question": "how do i get an email sent when a deal moves to negotiation",
            "category": "single",
            "expected": {
                "sales_manager@acme": {
                    "outcome": "answer",
                    "required": ["campaigns-deal-triggers#connect-a-stage-to-a-campaign"],
                },
                "sales_rep@globex": {
                    "outcome": "restricted",
                    "required": ["campaigns-deal-triggers#connect-a-stage-to-a-campaign"],
                    "missing_modules": ["campaigns"],
                },
            },
        }
    )
    assert q.expected["sales_rep@globex"].missing_modules == ["campaigns"]


@pytest.mark.parametrize(
    "change",
    [{"id": "42"}, {"category": "easy"}, {"expected": {}}, {"source": "llm"}],
    ids=["bad-id", "bad-category", "no-personas", "extra-field"],
)
def test_contract_rejects_bad_questions(change: dict[str, object]) -> None:
    raw: dict[str, object] = {
        "id": "q-0001",
        "question": "how do i log a call",
        "category": "single",
        "expected": {"sales_rep@acme": {"outcome": "answer", "required": ["a#b"]}},
    }
    with pytest.raises(ValidationError):
        GoldenQuestion.model_validate({**raw, **change})
