"""Synthetic docs: the plan, its checks, and (from S1.2.1 step C) the generator.

    python -m tools.docgen check    # validate data/docs/plan.yaml against the spec

The plan fixes everything evals and permissions depend on (doc ids, modules,
headings, so anchors) before any LLM is involved. Fail closed: any error
stops the run.
"""

import argparse
import contextlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Literal

import jsonschema
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from chatbot.ingest.anchors import slugify
from tools import spec as specmod

ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "data" / "docs"
PLAN_PATH = DOCS_DIR / "plan.yaml"
FRONTMATTER_SCHEMA_PATH = ROOT / "data" / "spec" / "doc_frontmatter.schema.json"

MIN_DOCS, MAX_DOCS = 40, 60
MIN_DOCS_PER_MODULE = 3
LONG_PROCEDURE_STEPS = 10

# Labels other parts of the repo already point at: the mock responder's
# citations and the eval example in CLAUDE.md. The corpus must keep them.
REQUIRED_LABELS = (
    "deals-stage-automation#triggers",
    "campaigns-triggered-emails#setup",
    "reports-dashboards#create-a-dashboard",
    "contacts-import#csv",
)

HardCase = Literal[
    "near_duplicate", "cross_reference", "long_procedure", "code_block", "table", "multi_module"
]
ALL_HARD_CASES: tuple[str, ...] = HardCase.__args__  # type: ignore[attr-defined]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Section(_Strict):
    heading: str = Field(min_length=1)
    level: Literal[2, 3] = 2
    steps: int | None = Field(default=None, ge=2)  # a numbered procedure of about N steps
    table: bool = False
    code: bool = False

    @property
    def anchor(self) -> str:
        return slugify(self.heading)


class PlannedDoc(_Strict):
    doc_id: str
    title: str = Field(min_length=1)
    modules: list[str] = Field(min_length=1)
    kind: Literal["module", "workflow"]
    workflow: str | None = None
    brief: str = Field(min_length=1)
    sections: list[Section] = Field(min_length=2)
    hard_cases: list[HardCase] = []
    related: list[str] = []

    @model_validator(mode="after")
    def _consistent(self) -> "PlannedDoc":
        if (self.kind == "workflow") != (self.workflow is not None):
            raise ValueError("`workflow` is required for workflow guides and only for them")
        if self.sections[0].level != 2:
            raise ValueError("the first section must be level 2")
        anchors = [s.anchor for s in self.sections]
        if "" in anchors:
            raise ValueError("a heading has no letters or digits, so no anchor")
        dupes = sorted(a for a, n in Counter(anchors).items() if n > 1)
        if dupes:
            raise ValueError(f"duplicate anchors {dupes}; headings must be unique within a doc")
        evidence = {
            "long_procedure": any((s.steps or 0) >= LONG_PROCEDURE_STEPS for s in self.sections),
            "code_block": any(s.code for s in self.sections),
            "table": any(s.table for s in self.sections),
            "multi_module": len(self.modules) >= 2,
            "near_duplicate": bool(self.related),
            "cross_reference": bool(self.related),
        }
        unbacked = [h for h in self.hard_cases if not evidence[h]]
        if unbacked:
            raise ValueError(f"hard_cases {unbacked} have nothing in the plan to back them")
        return self

    @property
    def anchors(self) -> list[str]:
        return [s.anchor for s in self.sections]

    @property
    def path(self) -> Path:
        folder = "workflows" if self.kind == "workflow" else self.modules[0]
        return DOCS_DIR / folder / f"{self.doc_id}.md"

    def frontmatter(self) -> dict[str, Any]:
        """Written by code from the plan; never taken from model output (rule 4)."""
        return {"doc_id": self.doc_id, "title": self.title, "modules": self.modules, "version": 1}


class Gap(_Strict):
    id: str
    modules: list[str] = Field(min_length=1)
    topic: str = Field(min_length=1)


class DocPlan(_Strict):
    plan_version: int = Field(ge=1)
    seed: int
    docs: list[PlannedDoc]
    gaps: list[Gap] = []


class PlanError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


def parse_plan(raw: Any) -> DocPlan:
    try:
        return DocPlan.model_validate(raw)
    except ValidationError as e:
        raise PlanError([_format(err, raw) for err in e.errors()]) from e


def _format(err: Any, raw: Any) -> str:
    """`docs/3/sections` -> `docs/deals-records/sections`: name the doc, not its index."""
    loc = [str(p) for p in err["loc"]]
    if len(loc) >= 2 and loc[0] == "docs" and loc[1].isdigit():
        with contextlib.suppress(KeyError, IndexError, TypeError):
            loc[1] = str(raw["docs"][int(loc[1])]["doc_id"])
    msg = str(err["msg"]).removeprefix("Value error, ")
    return f"{'/'.join(loc)}: {msg}"


def plan_errors(plan: DocPlan, spec: specmod.Spec, frontmatter_schema: dict[str, Any]) -> list[str]:
    """Checks that need the spec or the whole plan, not just one doc."""
    errors: list[str] = []
    known = spec.modules.keys()
    validator = jsonschema.Draft202012Validator(frontmatter_schema)
    ids = [d.doc_id for d in plan.docs]
    by_id = {d.doc_id: d for d in plan.docs}

    for dup in sorted(i for i, n in Counter(ids).items() if n > 1):
        errors.append(f"docs: duplicate doc_id {dup!r}")
    if not MIN_DOCS <= len(plan.docs) <= MAX_DOCS:
        errors.append(f"docs: {len(plan.docs)} planned, need {MIN_DOCS}-{MAX_DOCS}")

    for d in plan.docs:
        where = f"docs/{d.doc_id}"
        for e in validator.iter_errors(d.frontmatter()):
            errors.append(f"{where}: frontmatter {e.message}")
        unknown = sorted(set(d.modules) - known)
        if unknown:
            errors.append(f"{where}: unknown modules {unknown}")
        for r in d.related:
            if r == d.doc_id or r not in by_id:
                errors.append(f"{where}: related {r!r} is not another planned doc")

    # One guide per spec workflow, tagged with exactly the workflow's modules.
    guides = [d for d in plan.docs if d.kind == "workflow"]
    spec_workflows = {w.id: w for w in spec.workflows}
    for d in guides:
        w = spec_workflows.get(d.workflow or "")
        if w is None:
            errors.append(f"docs/{d.doc_id}: unknown workflow {d.workflow!r}")
        elif set(d.modules) != w.modules:
            errors.append(
                f"docs/{d.doc_id}: modules {sorted(d.modules)} must equal "
                f"workflow {w.id}'s {sorted(w.modules)}"
            )
    covered = Counter(d.workflow for d in guides)
    for wid in spec_workflows:
        if covered[wid] != 1:
            errors.append(f"workflows/{wid}: needs exactly one guide, found {covered[wid]}")

    module_docs = Counter(m for d in plan.docs if d.kind == "module" for m in d.modules)
    for m in known:
        if module_docs[m] < MIN_DOCS_PER_MODULE:
            errors.append(f"modules/{m}: {module_docs[m]} module docs, need {MIN_DOCS_PER_MODULE}")

    used = {h for d in plan.docs for h in d.hard_cases}
    for h in ALL_HARD_CASES:
        if h not in used:
            errors.append(f"hard_cases: no doc covers {h!r}")

    for label in REQUIRED_LABELS:
        doc_id, _, anchor = label.partition("#")
        if doc_id not in by_id or anchor not in by_id[doc_id].anchors:
            errors.append(f"required label {label!r} is not in the plan")

    gap_ids = [g.id for g in plan.gaps]
    for dup in sorted(i for i, n in Counter(gap_ids).items() if n > 1):
        errors.append(f"gaps: duplicate id {dup!r}")
    for g in plan.gaps:
        if g.id in by_id:
            errors.append(f"gaps/{g.id}: a planned doc has the same id")
        unknown = sorted(set(g.modules) - known)
        if unknown:
            errors.append(f"gaps/{g.id}: unknown modules {unknown}")
    return errors


def load_plan(path: Path = PLAN_PATH) -> DocPlan:
    """Load, parse and cross-check the plan; raise PlanError on any problem."""
    spec = specmod.parse(specmod.load_raw(specmod.SPEC_PATH.read_text()), specmod.load_schema())
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise PlanError([f"cannot parse plan: {e}"]) from e
    plan = parse_plan(raw)
    schema: dict[str, Any] = json.loads(FRONTMATTER_SCHEMA_PATH.read_text())
    errors = plan_errors(plan, spec, schema)
    if errors:
        raise PlanError(errors)
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--plan", type=Path, default=PLAN_PATH)
    args = parser.parse_args(argv)

    try:
        plan = load_plan(args.plan)
    except (PlanError, specmod.SpecError) as e:
        print(f"{args.plan}: invalid plan", file=sys.stderr)
        for err in e.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    kinds = Counter(d.kind for d in plan.docs)
    sections = sum(len(d.sections) for d in plan.docs)
    print(
        f"plan ok: {len(plan.docs)} docs ({kinds['module']} module, {kinds['workflow']} workflow), "
        f"{sections} sections, {len(plan.gaps)} gaps"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
