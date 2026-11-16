"""S1.3.1 step A: targets fix labels and personas; golden files are re-derived."""

import copy
import random
from pathlib import Path
from typing import Any

import pytest
import yaml
from tools.evalgen import (
    TARGETS_PATH,
    Target,
    Targets,
    build_targets,
    choose_personas,
    golden_errors,
    load_corpus,
    load_seeds,
    load_targets,
    render_targets,
    target_errors,
)

CORPUS = load_corpus()
SEEDS = load_seeds()
GUIDE_LABEL = "campaigns-deal-triggers#connect-a-stage-to-a-campaign"  # [campaigns, deals]


def with_target(**fields: Any) -> Targets:
    base = load_targets()
    t = Target(tid="t-999", personas=["sales_manager@acme"], hint="h", **fields)
    return Targets(seed=base.seed, seed_version=base.seed_version, targets=[*base.targets, t])


def errors_for_new(targets: Targets) -> list[str]:
    return [e for e in target_errors(targets, CORPUS) if e.startswith("t-999")]


# --- targets ------------------------------------------------------------------------------


def test_repo_targets_are_valid_and_fresh() -> None:
    assert target_errors(load_targets(), CORPUS) == []
    rebuilt = render_targets(build_targets(CORPUS, SEEDS))
    assert TARGETS_PATH.read_text() == rebuilt, "stale: run `make evals-targets`"


def test_targets_are_deterministic() -> None:
    assert build_targets(CORPUS, SEEDS) == build_targets(CORPUS, SEEDS)


def test_restricted_targets_pick_restricted_personas_and_an_answer_control() -> None:
    chosen = choose_personas([GUIDE_LABEL], "restricted", CORPUS, random.Random(1))
    allowed = [CORPUS.personas[p] for p in chosen]
    holds = [{"campaigns", "deals"} <= a for a in allowed]
    assert holds.count(False) == 2 and holds.count(True) == 1


def test_single_targets_prefer_a_persona_missing_exactly_one_module() -> None:
    chosen = choose_personas([GUIDE_LABEL], "single", CORPUS, random.Random(1))
    missing = [len({"campaigns", "deals"} - CORPUS.personas[p]) for p in chosen]
    assert missing[0] == 0 and missing[1] == 1


def test_multi_hop_a_guide_covers_is_rejected() -> None:
    targets = with_target(
        category="multi_hop",
        required=["deals-stage-automation#triggers", "campaigns-triggered-emails#setup"],
    )
    assert any(
        "covers ['campaigns', 'deals']; label it as single" in e for e in errors_for_new(targets)
    )


def test_orphaned_label_is_rejected() -> None:
    targets = with_target(category="single", required=["deals-stage-automation#stage-triggers"])
    assert any("orphaned label" in e for e in errors_for_new(targets))


def test_unanswerable_persona_without_the_gaps_module_is_rejected() -> None:
    base = load_targets()
    t = Target(
        tid="t-999",
        category="unanswerable",
        personas=["sales_rep@globex"],  # no quotes
        hint="e-signatures",
        gap="quote-e-signature",
    )
    targets = Targets(seed=base.seed, seed_version=base.seed_version, targets=[*base.targets, t])
    assert any("must hold the gap's modules" in e for e in errors_for_new(targets))


def test_restricted_target_without_a_restricted_persona_is_rejected() -> None:
    targets = with_target(category="restricted", required=[GUIDE_LABEL])  # manager has both
    assert any("restricted persona and an answer control" in e for e in errors_for_new(targets))


# --- golden files -------------------------------------------------------------------------

GOOD: dict[str, Any] = {
    "id": "q-0001",
    "question": "how do i email a deal's contacts when it reaches a stage",
    "category": "single",
    "expected": {
        "sales_manager@acme": {"outcome": "answer", "required": [GUIDE_LABEL]},
        "sales_rep@globex": {
            "outcome": "restricted",
            "required": [GUIDE_LABEL],
            "missing_modules": ["campaigns"],
        },
    },
}


def golden(tmp_path: Path, *questions: dict[str, Any]) -> list[Path]:
    p = tmp_path / "set.yaml"
    p.write_text(yaml.safe_dump(list(questions)))
    return [p]


def test_valid_golden_question_passes(tmp_path: Path) -> None:
    report = golden_errors(golden(tmp_path, GOOD), CORPUS)
    assert report.errors == [] and report.questions == 1


def test_stored_outcome_that_drifts_from_the_spec_fails(tmp_path: Path) -> None:
    q = copy.deepcopy(GOOD)
    q["expected"]["sales_rep@globex"] = {"outcome": "answer", "required": [GUIDE_LABEL]}
    errors = golden_errors(golden(tmp_path, q), CORPUS).errors
    assert any("stored answer" in e and "give restricted ['campaigns']" in e for e in errors)


def test_orphaned_golden_label_fails(tmp_path: Path) -> None:
    q = copy.deepcopy(GOOD)
    for e in q["expected"].values():
        e["required"] = ["campaigns-deal-triggers#no-such-section"]
    errors = golden_errors(golden(tmp_path, q), CORPUS).errors
    assert any("orphaned label" in e for e in errors)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (
            lambda q: q["expected"].update(
                {"ceo@acme": {"outcome": "answer", "required": [GUIDE_LABEL]}}
            ),
            "unknown persona",
        ),
        (
            lambda q: q["expected"]["sales_manager@acme"].update(
                required=["deals-records#create-a-deal"]
            ),
            "disagree on the required labels",
        ),
    ],
    ids=["unknown-persona", "inconsistent-labels"],
)
def test_bad_golden_question_fails(tmp_path: Path, change: Any, reason: str) -> None:
    q = copy.deepcopy(GOOD)
    change(q)
    assert any(reason in e for e in golden_errors(golden(tmp_path, q), CORPUS).errors)


def test_duplicate_ids_and_questions_fail(tmp_path: Path) -> None:
    other = copy.deepcopy(GOOD)
    other["question"] = "How do I email a deal's contacts, when it reaches a stage?"
    errors = golden_errors(golden(tmp_path, GOOD, other), CORPUS).errors
    assert any("id also used" in e for e in errors)
    assert any("same question as q-0001" in e for e in errors)


def test_unanswerable_with_labels_fails(tmp_path: Path) -> None:
    q = {
        "id": "q-0002",
        "question": "can i get e-signatures on quotes",
        "category": "unanswerable",
        "expected": {"sales_rep@orbit": {"outcome": "not_found", "required": [GUIDE_LABEL]}},
    }
    errors = golden_errors(golden(tmp_path, q), CORPUS).errors
    assert any("takes no labels" in e for e in errors)
