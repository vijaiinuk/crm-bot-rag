"""Synthetic eval questions: targets, checks, and (from S1.3.1 step B) generation.

    python -m tools.evalgen targets   # build evals/synthetic/targets.yaml (no LLM)
    python -m tools.evalgen check     # validate targets + every evals/golden/*.yaml
    python -m tools.evalgen check --require-all     # ... and every target has a question
    python -m tools.evalgen generate [--only TID ...] [--force]   # costs money
    python -m tools.evalgen sample [-n 20]          # questions to hand-review

A target fixes everything an eval trusts before any LLM runs: the category,
the required `doc_id#anchor` labels, and the personas. Expected outcomes are
derived by `chatbot.evals.golden`, never written by a model. Fail closed.
"""

import argparse
import random
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from chatbot.evals.golden import (
    LABELLED,
    Category,
    GoldenError,
    GoldenQuestion,
    expected_for,
    split_label,
)
from chatbot.ingest.anchors import headings_of
from tools import docgen
from tools import spec as specmod
from tools.docwriter import parse_doc

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_DIR = ROOT / "evals" / "synthetic"
SEEDS_PATH = SYNTHETIC_DIR / "seeds.yaml"
TARGETS_PATH = SYNTHETIC_DIR / "targets.yaml"
GOLDEN_DIR = ROOT / "evals" / "golden"

SEED = 20261116
# How many questions of each category the synthetic set aims for (>= 150 total).
QUOTAS: dict[str, int] = {
    "single": 60,
    "multi_hop": 26,  # 13 seeded pairs x 2 phrasings
    "restricted": 20,
    "adversarial": 15,  # 5 attack types x 3
    "unanswerable": 15,  # 6 gaps x 2-3 phrasings
    "out_of_scope": 15,
}
SKIP_ANCHORS = frozenset({"before-you-start"})  # prerequisites, not a task to ask about


# --- the corpus as evals see it -------------------------------------------------------


@dataclass(frozen=True)
class Corpus:
    """What labels resolve against: the docs as written, not the plan."""

    doc_modules: dict[str, frozenset[str]]
    anchors: dict[str, list[str]]  # doc_id -> anchors in order, from the files
    titles: dict[str, str]
    headings: dict[str, dict[str, str]]  # doc_id -> anchor -> heading text
    guides: dict[str, frozenset[str]]  # workflow guide doc_id -> modules
    personas: dict[str, frozenset[str]]
    gaps: dict[str, frozenset[str]]  # gap id -> modules
    gap_topics: dict[str, str]
    plan_order: list[str]


def load_corpus() -> Corpus:
    spec = docgen.load_spec()
    plan = docgen.load_plan(spec=spec)
    anchors: dict[str, list[str]] = {}
    headings: dict[str, dict[str, str]] = {}
    for d in plan.docs:
        if not d.path.exists():
            raise GoldenError(f"{d.doc_id}: doc file missing; run `make docs-check`")
        _, body = parse_doc(d.path.read_text())
        hs = headings_of(body)
        anchors[d.doc_id] = [h.anchor for h in hs]
        headings[d.doc_id] = {h.anchor: h.text for h in hs}
    return Corpus(
        doc_modules={d.doc_id: frozenset(d.modules) for d in plan.docs},
        anchors=anchors,
        titles={d.doc_id: d.title for d in plan.docs},
        headings=headings,
        guides={d.doc_id: frozenset(d.modules) for d in plan.docs if d.kind == "workflow"},
        personas=specmod.derive_personas(spec),
        gaps={g.id: frozenset(g.modules) for g in plan.gaps},
        gap_topics={g.id: g.topic for g in plan.gaps},
        plan_order=[d.doc_id for d in plan.docs],
    )


def label_errors(labels: list[str], corpus: Corpus) -> list[str]:
    errors = []
    for label in labels:
        try:
            doc_id, anchor = split_label(label)
        except GoldenError as e:
            errors.append(str(e))
            continue
        if doc_id not in corpus.anchors:
            errors.append(f"{label}: no such doc")
        elif anchor not in corpus.anchors[doc_id]:
            errors.append(f"{label}: no such section (orphaned label)")
    return errors


# --- seeds and targets ------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MultiHopSeed(_Strict):
    labels: list[str] = Field(min_length=2)
    task: str


class AttackSeed(_Strict):
    type: str
    how: str


class Seeds(_Strict):
    seed_version: int
    multi_hop: list[MultiHopSeed]
    adversarial: list[AttackSeed]
    out_of_scope: list[str]


class Target(_Strict):
    """One question to write: everything but the wording."""

    tid: str = Field(pattern=r"^t-\d{3}$")
    category: Category
    required: list[str] = []
    personas: list[str] = Field(min_length=1)
    hint: str  # what the question is about, for the question writer
    attack: str | None = None  # adversarial: how the user tries to get around access
    gap: str | None = None  # unanswerable: which planned gap


class Targets(_Strict):
    seed: int
    seed_version: int
    targets: list[Target]


def load_seeds(path: Path = SEEDS_PATH) -> Seeds:
    return Seeds.model_validate(yaml.safe_load(path.read_text()))


def _outcomes(required: list[str], corpus: Corpus) -> dict[str, tuple[str, int]]:
    """persona -> (outcome, number of missing modules)."""
    out: dict[str, tuple[str, int]] = {}
    for pid, allowed in corpus.personas.items():
        e = expected_for("single", required, allowed, corpus.doc_modules)
        out[pid] = (e.outcome, len(e.missing_modules))
    return out


def choose_personas(
    required: list[str], category: str, corpus: Corpus, rng: random.Random
) -> list[str]:
    """2-3 personas that make the question informative.

    single/multi_hop: one who gets an answer, one restricted (missing exactly
    one module if possible), one more. restricted/adversarial: two restricted
    plus one answer persona as a control.
    """
    outcomes = _outcomes(required, corpus)
    answer = sorted(p for p, (o, _) in outcomes.items() if o == "answer")
    restricted = sorted(p for p, (o, _) in outcomes.items() if o == "restricted")
    missing_one = [p for p in restricted if outcomes[p][1] == 1]
    rng.shuffle(answer)
    rng.shuffle(restricted)
    rng.shuffle(missing_one)

    def take(pool: list[str], chosen: list[str]) -> None:
        for p in pool:
            if p not in chosen:
                chosen.append(p)
                return

    chosen: list[str] = []
    if category in ("restricted", "adversarial"):
        take(missing_one or restricted, chosen)
        take(restricted, chosen)
        take(answer, chosen)
    else:
        take(answer, chosen)
        take(missing_one or restricted, chosen)
        take([p for p in answer + restricted if p not in chosen], chosen)
    return chosen


def build_targets(corpus: Corpus, seeds: Seeds, seed: int = SEED) -> Targets:
    rng = random.Random(seed)  # noqa: S311 - reproducible sampling, not security
    out: list[dict[str, Any]] = []

    def section(doc_id: str, anchor: str) -> str:
        return f"{corpus.titles[doc_id]} > {corpus.headings[doc_id][anchor]}"

    # single: one section per doc, then second sections until the quota.
    askable = {
        d: [a for a in corpus.anchors[d] if a not in SKIP_ANCHORS] for d in corpus.plan_order
    }
    used: set[str] = set()
    singles: list[str] = []
    for d in corpus.plan_order:
        a = rng.choice(askable[d])
        singles.append(f"{d}#{a}")
    extra_docs = [d for d in corpus.plan_order if len(askable[d]) >= 3]
    rng.shuffle(extra_docs)
    for d in extra_docs[: QUOTAS["single"] - len(singles)]:
        a = rng.choice([a for a in askable[d] if f"{d}#{a}" not in singles])
        singles.append(f"{d}#{a}")
    for label in singles:
        used.add(label)
        d, a = split_label(label)
        out.append({"category": "single", "required": [label], "hint": f"how to: {section(d, a)}"})

    # multi_hop: each seeded pair, twice.
    for s in seeds.multi_hop:
        for _ in range(2):
            out.append({"category": "multi_hop", "required": list(s.labels), "hint": s.task})

    # restricted and adversarial: sections some personas can see and others
    # can't (every persona has core and contacts, so those never qualify).
    def splits(label: str) -> bool:
        seen = {o for o, _ in _outcomes([label], corpus).values()}
        return seen == {"answer", "restricted"}

    non_core = [f"{d}#{a}" for d in corpus.plan_order for a in askable[d] if splits(f"{d}#{a}")]
    fresh = [label for label in non_core if label not in used]
    rng.shuffle(fresh)
    for label in fresh[: QUOTAS["restricted"]]:
        used.add(label)
        d, a = split_label(label)
        out.append(
            {"category": "restricted", "required": [label], "hint": f"how to: {section(d, a)}"}
        )
    pool = [label for label in non_core if label not in used] or non_core
    rng.shuffle(pool)
    per_attack = QUOTAS["adversarial"] // len(seeds.adversarial)
    for i, attack in enumerate(seeds.adversarial):
        for label in pool[i * per_attack : (i + 1) * per_attack]:
            d, a = split_label(label)
            out.append(
                {
                    "category": "adversarial",
                    "required": [label],
                    "hint": f"how to: {section(d, a)}",
                    "attack": f"{attack.type}: {attack.how}",
                }
            )

    # unanswerable: the planned gaps, 2-3 phrasings each.
    gap_ids = list(corpus.gaps)
    for i in range(QUOTAS["unanswerable"]):
        g = gap_ids[i % len(gap_ids)]
        out.append({"category": "unanswerable", "gap": g, "hint": corpus.gap_topics[g]})

    # out_of_scope: one per seeded theme.
    for theme in seeds.out_of_scope:
        out.append({"category": "out_of_scope", "hint": theme})

    targets = []
    for n, t in enumerate(out, start=1):
        category = t["category"]
        if category in LABELLED:
            personas = choose_personas(t["required"], category, corpus, rng)
        elif category == "unanswerable":
            holders = sorted(p for p, m in corpus.personas.items() if corpus.gaps[t["gap"]] <= m)
            personas = rng.sample(holders, k=min(2, len(holders)))
        else:
            personas = rng.sample(sorted(corpus.personas), k=2)
        targets.append(Target(tid=f"t-{n:03d}", personas=personas, **t))
    return Targets(seed=seed, seed_version=seeds.seed_version, targets=targets)


def render_targets(targets: Targets) -> str:
    header = (
        "# GENERATED by `make evals-targets` from evals/synthetic/seeds.yaml and the\n"
        "# doc plan. Do not edit by hand: change the seeds or tools/evalgen.py instead.\n"
        "# Each target fixes a question's category, labels and personas; the LLM only\n"
        "# writes its wording, and expected outcomes are derived by code.\n"
    )
    body = targets.model_dump(exclude_defaults=True)
    return header + yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=100)


def load_targets(path: Path = TARGETS_PATH) -> Targets:
    try:
        return Targets.model_validate(yaml.safe_load(path.read_text()))
    except (OSError, yaml.YAMLError, ValidationError) as e:
        raise GoldenError(f"{path}: {e}") from e


# --- checks -----------------------------------------------------------------------------


def target_errors(targets: Targets, corpus: Corpus) -> list[str]:
    errors: list[str] = []
    counts: Counter[str] = Counter(t.category for t in targets.targets)
    for category, quota in QUOTAS.items():
        if counts[category] < quota:
            errors.append(f"{category}: {counts[category]} targets, need {quota}")
    tids = [t.tid for t in targets.targets]
    errors += [f"duplicate tid {t}" for t, n in Counter(tids).items() if n > 1]

    for t in targets.targets:
        where = t.tid
        unknown = [p for p in t.personas if p not in corpus.personas]
        if unknown:
            errors.append(f"{where}: unknown personas {unknown}")
            continue
        if t.category in LABELLED:
            if not t.required:
                errors.append(f"{where}: {t.category} needs required labels")
                continue
            if bad := label_errors(t.required, corpus):
                errors += [f"{where}: {e}" for e in bad]
                continue
            outcomes = {_outcomes(t.required, corpus)[p][0] for p in t.personas}
            if t.category in ("restricted", "adversarial") and outcomes != {"answer", "restricted"}:
                errors.append(f"{where}: needs a restricted persona and an answer control")
        elif t.required:
            errors.append(f"{where}: {t.category} takes no labels")
        if t.category == "multi_hop":
            docs = {split_label(label)[0] for label in t.required}
            needed = frozenset().union(*(corpus.doc_modules[d] for d in docs))
            if len(docs) < 2:
                errors.append(f"{where}: multi_hop needs sections from 2+ docs")
            for guide, modules in corpus.guides.items():
                if modules == needed:
                    errors.append(f"{where}: {guide} covers {sorted(needed)}; label it as single")
        if t.category == "unanswerable":
            gap = corpus.gaps.get(t.gap or "")
            if gap is None:
                errors.append(f"{where}: unknown gap {t.gap!r}")
            elif any(not gap <= corpus.personas[p] for p in t.personas):
                errors.append(f"{where}: unanswerable personas must hold the gap's modules")
        if t.category == "adversarial" and not t.attack:
            errors.append(f"{where}: adversarial needs an attack")
    return errors


def _normalise(question: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", question.lower()).strip()


@dataclass
class GoldenReport:
    questions: int = 0
    errors: list[str] = field(default_factory=list)
    by_category: Counter[str] = field(default_factory=Counter)


def golden_errors(paths: list[Path], corpus: Corpus) -> GoldenReport:
    """Every golden file: contract, labels resolve, outcomes match derivation."""
    report = GoldenReport()
    seen_ids: dict[str, Path] = {}
    seen_text: dict[str, str] = {}
    for path in paths:
        raw = yaml.safe_load(path.read_text()) or []
        if not isinstance(raw, list):
            report.errors.append(f"{path.name}: expected a list of questions")
            continue
        for i, item in enumerate(raw):
            try:
                q = GoldenQuestion.model_validate(item)
            except ValidationError as e:
                report.errors.append(f"{path.name}[{i}]: {e.errors()[0]['msg']}")
                continue
            report.questions += 1
            report.by_category[q.category] += 1
            where = f"{path.name}:{q.id}"
            if q.id in seen_ids:
                report.errors.append(f"{where}: id also used in {seen_ids[q.id].name}")
            seen_ids[q.id] = path
            norm = _normalise(q.question)
            if norm in seen_text:
                report.errors.append(f"{where}: same question as {seen_text[norm]}")
            seen_text[norm] = q.id

            requireds = {tuple(e.required) for e in q.expected.values()}
            if len(requireds) > 1:
                report.errors.append(f"{where}: personas disagree on the required labels")
            required = list(next(iter(requireds)))
            if bad := label_errors(required, corpus):
                report.errors += [f"{where}: {e}" for e in bad]
                continue
            for pid, got in q.expected.items():
                if pid not in corpus.personas:
                    report.errors.append(f"{where}: unknown persona {pid!r}")
                    continue
                try:
                    want = expected_for(
                        q.category, required, corpus.personas[pid], corpus.doc_modules
                    )
                except GoldenError as e:
                    report.errors.append(f"{where}/{pid}: {e}")
                    continue
                if got != want:
                    report.errors.append(
                        f"{where}/{pid}: stored {got.outcome} {got.missing_modules or ''} but the "
                        f"spec and docs give {want.outcome} {want.missing_modules or ''}"
                    )
    return report


def golden_paths(golden_dir: Path = GOLDEN_DIR) -> list[Path]:
    return sorted(golden_dir.glob("*.yaml")) if golden_dir.exists() else []


# --- CLI --------------------------------------------------------------------------------


def _generate(corpus: Corpus, only: list[str], force: bool) -> int:
    import asyncio

    from chatbot.adapters.litellm_client import LiteLLMClient
    from chatbot.config import Settings
    from chatbot.models_config import load_models_config
    from chatbot.ports.llm import LLMError
    from tools import questionwriter as qw

    settings = Settings()
    try:
        client = LiteLLMClient(
            load_models_config(settings.models_path),
            openrouter_api_key=settings.openrouter_api_key,
        )
    except LLMError as e:
        print(f"cannot generate: {e}", file=sys.stderr)
        return 1
    targets = load_targets()
    outcomes = asyncio.run(
        qw.generate(targets, corpus, qw.load_prompt(), client, only=only, force=force)
    )
    if not outcomes:
        print("nothing to generate (all selected questions exist; use --force to rewrite)")
    tokens_in = tokens_out = 0
    for o in outcomes:
        tokens_in += sum(c.usage.input_tokens for c in o.calls)
        tokens_out += sum(c.usage.output_tokens for c in o.calls)
        if o.question:
            print(f"wrote {o.tid} (attempts {o.attempts}, copy {o.copy:.0%}): {o.question}")
        else:
            print(f"FAILED {o.tid} (attempts {o.attempts})")
            for err in o.errors:
                print(f"    - {err}", file=sys.stderr)
    print(f"tokens: {tokens_in} in, {tokens_out} out")
    return 0 if all(o.question for o in outcomes) else 1


def _sample(n: int) -> int:
    from tools import questionwriter as qw

    golden = qw.load_golden()
    targets = {qw.qid(t): t for t in load_targets().targets}
    for q_id in qw.review_sample(golden, SEED, n):
        q = golden[q_id]
        t = targets[q_id]
        outcomes = ", ".join(
            f"{p}: {e['outcome']}"
            + (f" (no {', '.join(e['missing_modules'])})" if e.get("missing_modules") else "")
            for p, e in q["expected"].items()
        )
        labels = ", ".join(t.required) or t.gap or "-"
        print(f"{q_id} [{q['category']}] {q['question']}\n    labels: {labels}\n    {outcomes}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["targets", "check", "generate", "sample"])
    parser.add_argument("--require-all", action="store_true", help="check: every target written")
    parser.add_argument("--only", nargs="+", default=[], metavar="TID", help="generate: these")
    parser.add_argument("--force", action="store_true", help="generate: rewrite existing")
    parser.add_argument("-n", type=int, default=20, help="sample: how many questions")
    args = parser.parse_args(argv)

    if args.command == "sample":
        return _sample(args.n)
    try:
        corpus = load_corpus()
        if args.command == "generate":
            return _generate(corpus, args.only, args.force)
        if args.command == "targets":
            targets = build_targets(corpus, load_seeds())
            if errors := target_errors(targets, corpus):
                for e in errors:
                    print(f"  - {e}", file=sys.stderr)
                return 1
            TARGETS_PATH.write_text(render_targets(targets))
            counts = Counter(t.category for t in targets.targets)
            where = TARGETS_PATH.relative_to(ROOT)
            print(f"wrote {where}: {len(targets.targets)} targets {dict(counts)}")
            return 0

        errors = target_errors(load_targets(), corpus) if TARGETS_PATH.exists() else []
        if not TARGETS_PATH.exists():
            errors.append(f"{TARGETS_PATH.relative_to(ROOT)} missing; run `make evals-targets`")
        elif render_targets(build_targets(corpus, load_seeds())) != TARGETS_PATH.read_text():
            errors.append(
                "targets.yaml is stale vs seeds.yaml and the docs; run `make evals-targets`"
            )
        report = golden_errors(golden_paths(), corpus)
        errors += report.errors
        if args.require_all and TARGETS_PATH.exists():
            from tools import questionwriter as qw

            written = qw.load_golden()
            missing = [t.tid for t in load_targets().targets if qw.qid(t) not in written]
            if missing:
                errors.append(
                    f"{len(missing)} targets have no question yet: {', '.join(missing[:10])}"
                )
    except (GoldenError, docgen.PlanError, specmod.SpecError, ValidationError) as e:
        print(f"cannot check evals: {e}", file=sys.stderr)
        return 1

    for err in errors:
        print(f"  - {err}", file=sys.stderr)
    print(
        f"evals: {report.questions} golden questions {dict(report.by_category)}, "
        f"{len(errors)} errors"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
