"""S1.2.1 step A: the doc plan fixes ids, modules and anchors before any LLM runs."""

import copy
import json
from typing import Any

import yaml
from tools.docgen import PlanError, load_plan, parse_plan, plan_errors

from tools import docgen
from tools import spec as specmod

SPEC = specmod.parse(specmod.load_raw(specmod.SPEC_PATH.read_text()), specmod.load_schema())
FM_SCHEMA: dict[str, Any] = json.loads(docgen.FRONTMATTER_SCHEMA_PATH.read_text())
REPO_RAW: dict[str, Any] = yaml.safe_load(docgen.PLAN_PATH.read_text())


def repo_raw() -> dict[str, Any]:
    return copy.deepcopy(REPO_RAW)


def doc(raw: dict[str, Any], doc_id: str) -> dict[str, Any]:
    return next(d for d in raw["docs"] if d["doc_id"] == doc_id)


def errors_of(raw: dict[str, Any]) -> str:
    try:
        plan = parse_plan(raw)
    except PlanError as e:
        return "\n".join(e.errors)
    return "\n".join(plan_errors(plan, SPEC, FM_SCHEMA))


# --- the repo plan --------------------------------------------------------------------


def test_repo_plan_is_valid() -> None:
    plan = load_plan()
    assert docgen.MIN_DOCS <= len(plan.docs) <= docgen.MAX_DOCS


def test_required_labels_exist() -> None:
    """The mock responder and the CLAUDE.md eval example point at these."""
    anchors = {d.doc_id: d.anchors for d in load_plan().docs}
    for label in docgen.REQUIRED_LABELS:
        doc_id, _, anchor = label.partition("#")
        assert anchor in anchors[doc_id], label


def test_every_spec_workflow_has_one_guide_with_all_its_modules() -> None:
    guides = {d.workflow: d for d in load_plan().docs if d.kind == "workflow"}
    for w in SPEC.workflows:
        assert set(guides[w.id].modules) == w.modules


def test_frontmatter_comes_from_the_plan() -> None:
    d = next(d for d in load_plan().docs if d.doc_id == "deals-forecasting")
    assert d.frontmatter() == {
        "doc_id": "deals-forecasting",
        "title": "Forecasting deals",
        "modules": ["deals", "reports"],
        "version": 1,
    }
    assert d.path == docgen.DOCS_DIR / "deals" / "deals-forecasting.md"


def test_workflow_guides_live_in_workflows_folder() -> None:
    d = next(d for d in load_plan().docs if d.doc_id == "campaigns-deal-triggers")
    assert d.path == docgen.DOCS_DIR / "workflows" / "campaigns-deal-triggers.md"


# --- fail closed ------------------------------------------------------------------------


def test_unknown_module_is_rejected() -> None:
    raw = repo_raw()
    doc(raw, "deals-records")["modules"] = ["dealz"]
    assert "docs/deals-records: unknown modules ['dealz']" in errors_of(raw)


def test_duplicate_anchor_within_a_doc_is_rejected() -> None:
    raw = repo_raw()
    doc(raw, "deals-records")["sections"].append({"heading": "Create a deal!"})
    assert "duplicate anchors ['create-a-deal']" in errors_of(raw)


def test_duplicate_doc_id_is_rejected() -> None:
    raw = repo_raw()
    raw["docs"].append(copy.deepcopy(doc(raw, "deals-records")))
    assert "duplicate doc_id 'deals-records'" in errors_of(raw)


def test_workflow_guide_with_wrong_modules_is_rejected() -> None:
    raw = repo_raw()
    doc(raw, "campaigns-deal-triggers")["modules"] = ["deals", "reports"]
    assert "must equal workflow deal-stage-email's" in errors_of(raw)


def test_missing_workflow_guide_is_rejected() -> None:
    raw = repo_raw()
    raw["docs"] = [d for d in raw["docs"] if d["doc_id"] != "deals-follow-up-tasks"]
    assert "workflows/deal-follow-ups: needs exactly one guide, found 0" in errors_of(raw)


def test_unbacked_hard_case_is_rejected() -> None:
    raw = repo_raw()
    doc(raw, "deals-records")["hard_cases"] = ["long_procedure"]
    assert "hard_cases ['long_procedure'] have nothing in the plan" in errors_of(raw)


def test_dangling_related_doc_is_rejected() -> None:
    raw = repo_raw()
    doc(raw, "deals-records")["related"] = ["no-such-doc"]
    assert "related 'no-such-doc' is not another planned doc" in errors_of(raw)


def test_dropping_a_required_label_is_rejected() -> None:
    raw = repo_raw()
    doc(raw, "deals-stage-automation")["sections"][0]["heading"] = "Stage triggers"
    assert "required label 'deals-stage-automation#triggers'" in errors_of(raw)


def test_gap_colliding_with_a_doc_is_rejected() -> None:
    raw = repo_raw()
    raw["gaps"].append({"id": "deals-records", "modules": ["deals"], "topic": "t"})
    assert "gaps/deals-records: a planned doc has the same id" in errors_of(raw)


def test_bad_doc_id_fails_the_frontmatter_schema() -> None:
    raw = repo_raw()
    doc(raw, "deals-records")["doc_id"] = "Deals Records"
    assert "frontmatter 'Deals Records' does not match" in errors_of(raw)


def test_per_doc_errors_name_the_doc() -> None:
    raw = repo_raw()
    doc(raw, "deals-records")["sections"].append({"heading": "Create a deal!"})
    assert errors_of(raw).startswith("docs/deals-records:")


def test_unknown_field_is_rejected() -> None:
    raw = repo_raw()
    doc(raw, "deals-records")["modules_extra"] = ["campaigns"]
    assert "Extra inputs are not permitted" in errors_of(raw)
