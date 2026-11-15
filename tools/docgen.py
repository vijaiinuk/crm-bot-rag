"""Synthetic docs: the plan, its checks, and the generator CLI.

    python -m tools.docgen check                  # plan + every doc written so far
    python -m tools.docgen check --require-all    # ... and every planned doc exists
    python -m tools.docgen generate [--only ID ...] [--force]   # costs money
    python -m tools.docgen sample [-n 10]         # docs to hand-review

The plan fixes everything evals and permissions depend on (doc ids, modules,
headings, so anchors) before any LLM is involved. Fail closed: any error
stops the run.
"""

import argparse
import asyncio
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


def load_spec() -> specmod.Spec:
    return specmod.parse(specmod.load_raw(specmod.SPEC_PATH.read_text()), specmod.load_schema())


def load_plan(path: Path = PLAN_PATH, spec: specmod.Spec | None = None) -> DocPlan:
    """Load, parse and cross-check the plan; raise PlanError on any problem."""
    spec = spec or load_spec()
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


def _check(plan: DocPlan, spec: specmod.Spec, require_all: bool) -> int:
    from tools.docwriter import check_corpus

    report = check_corpus(plan, spec)
    for doc_id, flags in report.flags.items():
        print(f"flag {doc_id}: {'; '.join(flags)} (review for content leaks)")
    if report.edited:
        print(f"edited by hand since generation: {', '.join(report.edited)}")
    errors = list(report.errors)
    if require_all and report.missing:
        errors.append(f"{len(report.missing)} planned docs missing: {', '.join(report.missing)}")
    for err in errors:
        print(f"  - {err}", file=sys.stderr)
    print(
        f"docs: {report.present}/{len(plan.docs)} written, {len(report.flags)} flagged, "
        f"{len(errors)} errors"
    )
    return 1 if errors else 0


def _generate(plan: DocPlan, spec: specmod.Spec, only: list[str], force: bool) -> int:
    from chatbot.adapters.litellm_client import LiteLLMClient
    from chatbot.config import Settings
    from chatbot.models_config import load_models_config
    from chatbot.ports.llm import LLMError
    from tools.docwriter import generate, load_prompt

    settings = Settings()
    try:
        client = LiteLLMClient(
            load_models_config(settings.models_path),
            openrouter_api_key=settings.openrouter_api_key,
        )
    except LLMError as e:
        print(f"cannot generate: {e}", file=sys.stderr)
        return 1
    outcomes = asyncio.run(generate(plan, spec, load_prompt(), client, only=only, force=force))
    if not outcomes:
        print("nothing to generate (all selected docs exist; use --force to rewrite)")
    tokens_in = tokens_out = 0
    for o in outcomes:
        tokens_in += sum(c.usage.input_tokens for c in o.calls)
        tokens_out += sum(c.usage.output_tokens for c in o.calls)
        status = "wrote" if o.written else "FAILED"
        print(f"{status} {o.doc_id} (attempts: {o.attempts})")
        for err in o.errors:
            print(f"    - {err}", file=sys.stderr)
        for f in o.flags:
            print(f"    flag: {f}")
    print(f"tokens: {tokens_in} in, {tokens_out} out")
    return 0 if all(o.written for o in outcomes) else 1


def _sample(plan: DocPlan, spec: specmod.Spec, n: int) -> int:
    from tools.docwriter import check_corpus, review_sample

    report = check_corpus(plan, spec)
    for doc_id in review_sample(plan, report, n):
        doc = next(d for d in plan.docs if d.doc_id == doc_id)
        note = f"  <- flagged: {'; '.join(report.flags[doc_id])}" if doc_id in report.flags else ""
        print(f"{doc.path.relative_to(ROOT)}{note}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["check", "generate", "sample"])
    parser.add_argument("--plan", type=Path, default=PLAN_PATH)
    parser.add_argument("--require-all", action="store_true", help="check: fail on missing docs")
    parser.add_argument("--only", nargs="+", default=[], metavar="DOC_ID", help="generate: these")
    parser.add_argument("--force", action="store_true", help="generate: rewrite existing docs")
    parser.add_argument("-n", type=int, default=10, help="sample: how many docs")
    args = parser.parse_args(argv)

    try:
        spec = load_spec()
        plan = load_plan(args.plan, spec)
    except (PlanError, specmod.SpecError) as e:
        print(f"{args.plan}: invalid plan", file=sys.stderr)
        for err in e.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    if args.command == "generate":
        return _generate(plan, spec, args.only, args.force)
    if args.command == "sample":
        return _sample(plan, spec, args.n)

    kinds = Counter(d.kind for d in plan.docs)
    sections = sum(len(d.sections) for d in plan.docs)
    print(
        f"plan ok: {len(plan.docs)} docs ({kinds['module']} module, {kinds['workflow']} workflow), "
        f"{sections} sections, {len(plan.gaps)} gaps"
    )
    return _check(plan, spec, args.require_all)


if __name__ == "__main__":
    sys.exit(main())
