"""The golden eval set: its YAML contract and how expected outcomes are derived.

Contract (CLAUDE.md, evals/golden/*.yaml):

    - id: q-0042
      question: "how do i get an email sent when a deal moves to negotiation"
      category: single
      expected:
        sales_manager@acme: { outcome: answer, required: [campaigns-deal-triggers#setup] }
        sales_rep@globex:   { outcome: restricted, required: [...], missing_modules: [campaigns] }

Labels are `doc_id#anchor`, never chunk IDs. For label-based categories the
per-persona outcome is *derived* from the labels' doc modules and the
persona's allowed modules, never judged by a person or an LLM.
"""

from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Outcome = Literal["answer", "restricted", "not_found", "out_of_scope"]
Category = Literal[
    "single", "multi_hop", "unanswerable", "out_of_scope", "restricted", "adversarial"
]
# Categories whose outcome follows from `required` labels and modules.
LABELLED: frozenset[str] = frozenset({"single", "multi_hop", "restricted", "adversarial"})


class GoldenError(ValueError):
    """A label or question that can't be resolved. Callers must fail, not guess."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Expected(_Strict):
    """What one persona should get for one question."""

    outcome: Outcome
    required: list[str] = Field(default_factory=list)  # doc_id#anchor
    missing_modules: list[str] = Field(default_factory=list)


class GoldenQuestion(_Strict):
    id: str = Field(pattern=r"^q-\d{4}$")
    question: str = Field(min_length=5, max_length=500)
    category: Category
    expected: dict[str, Expected] = Field(min_length=1)  # persona id -> expectation


def split_label(label: str) -> tuple[str, str]:
    doc_id, sep, anchor = label.partition("#")
    if not sep or not doc_id or not anchor:
        raise GoldenError(f"label {label!r} must be doc_id#anchor")
    return doc_id, anchor


def derive_expected(
    required: Sequence[str],
    allowed: frozenset[str],
    doc_modules: Mapping[str, frozenset[str]],
) -> Expected:
    """`answer` if the persona holds every module of every required doc;
    otherwise `restricted`, listing exactly the modules they lack."""
    if not required:
        raise GoldenError("no required labels to derive an outcome from")
    needed: set[str] = set()
    for label in required:
        doc_id, _ = split_label(label)
        if doc_id not in doc_modules:
            raise GoldenError(f"label {label!r}: unknown doc {doc_id!r}")
        needed |= doc_modules[doc_id]  # rule 5: every module of every doc
    missing = sorted(needed - allowed)
    if missing:
        return Expected(outcome="restricted", required=list(required), missing_modules=missing)
    return Expected(outcome="answer", required=list(required))


def expected_for(
    category: Category,
    required: Sequence[str],
    allowed: frozenset[str],
    doc_modules: Mapping[str, frozenset[str]],
) -> Expected:
    """Expected outcome for any category: derived for labelled categories,
    fixed for `unanswerable` (not_found) and `out_of_scope`."""
    if category in LABELLED:
        return derive_expected(required, allowed, doc_modules)
    if required:
        raise GoldenError(f"category {category!r} takes no labels, got {list(required)}")
    return Expected(outcome="not_found" if category == "unanswerable" else "out_of_scope")
