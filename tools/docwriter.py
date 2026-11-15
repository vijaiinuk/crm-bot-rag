"""Writes synthetic doc bodies with an LLM and checks them against the plan.

The model writes prose only. Frontmatter (so modules, rule 4) comes from the
plan, and a body whose headings differ from the plan is rejected, because
evals label `doc_id#anchor`.
"""

import asyncio
import hashlib
import random
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from string import Template
from typing import Any

import yaml

from chatbot.ingest.anchors import slugify
from chatbot.ports.llm import Completion, LLMClient, LLMError, Message
from tools import spec as specmod
from tools.docgen import DOCS_DIR, LONG_PROCEDURE_STEPS, ROOT, DocPlan, PlannedDoc

PROMPT_ID = "docgen_v3"
PROMPT_PATH = ROOT / "prompts" / f"{PROMPT_ID}.md"
MANIFEST_PATH = DOCS_DIR / "MANIFEST.yaml"
MODEL_ROLE = "docgen"
MAX_ATTEMPTS = 2  # one retry, with the rule violations fed back
CONCURRENCY = 4

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_NUMBERED = re.compile(r"^\s*\d+\.\s+\S")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)\Z", re.DOTALL)


# --- prompt -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Prompt:
    system: Template
    user: Template


def load_prompt(path: Path = PROMPT_PATH) -> Prompt:
    parts: dict[str, list[str]] = {}
    current: str | None = None
    for line in path.read_text().splitlines():
        if m := re.fullmatch(r"=== (system|user) ===", line.strip()):
            current = m.group(1)
            parts[current] = []
        elif current:
            parts[current].append(line)
    if set(parts) != {"system", "user"}:
        raise ValueError(f"{path}: needs a `=== system ===` and a `=== user ===` part")
    return Prompt(
        system=Template("\n".join(parts["system"]).strip()),
        user=Template("\n".join(parts["user"]).strip()),
    )


def _section_line(level: int, heading: str, needs: list[str]) -> str:
    marks = "#" * level
    return f"- `{marks} {heading}`" + (f" ({'; '.join(needs)})" if needs else " (prose)")


def word_range(doc: PlannedDoc) -> tuple[int, int]:
    steps = sum(s.steps or 0 for s in doc.sections)
    low = 60 * len(doc.sections) + 10 * steps
    return low, 2 * low


def build_messages(
    doc: PlannedDoc, plan: DocPlan, spec: specmod.Spec, prompt: Prompt
) -> list[Message]:
    titles = {d.doc_id: d.title for d in plan.docs}
    modules = "\n".join(
        f"- {m.display_name} (`{m.name}`): {m.description} "
        f"Things in it: {', '.join(m.entities)}. On-screen labels: {', '.join(m.ui_labels)}."
        for name in doc.modules
        if (m := spec.modules[name])
    )
    sections = []
    for s in doc.sections:
        needs = []
        if s.steps:
            needs.append(f"procedure: a numbered list of about {s.steps} steps")
        if s.table:
            needs.append("table")
        if s.code:
            needs.append("code block")
        sections.append(_section_line(s.level, s.heading, needs))

    # Only this doc's own modules: the model is never handed another module's
    # details to leak. Core facts go only to core docs; giving them to every
    # doc made the same sentences repeat across the corpus (v2 pilot).
    facts = [f"- {f}" for name in doc.modules for f in spec.modules[name].facts]
    workflow = ""
    if doc.workflow:
        w = next(w for w in spec.workflows if w.id == doc.workflow)
        facts += [f"- {f}" for f in w.facts]
        workflow = (
            f"This is an end-to-end guide for the task: {w.title}. "
            f"Prerequisites to state up front: {', '.join(w.prerequisites)}.\n"
        )
    related = ""
    if doc.related:
        refs = ", ".join(f"*{titles[r]}*" for r in doc.related)
        related = (
            f"Related documents you may point to by title (do not repeat their content): {refs}.\n"
        )
    gaps = "\n".join(f"- {g.topic}" for g in plan.gaps) or "- (none)"
    low, high = word_range(doc)

    user = prompt.user.substitute(
        title=doc.title,
        brief=doc.brief,
        modules=modules,
        facts="\n".join(facts),
        workflow=workflow,
        sections="\n".join(sections),
        related=related,
        gaps=gaps,
        min_words=low,
        max_words=high,
    )
    return [Message("system", prompt.system.substitute()), Message("user", user)]


# --- checking a body --------------------------------------------------------------------


def split_sections(body: str) -> list[tuple[int, str, str]]:
    """(level, heading text, section text) for each heading outside code fences."""
    out: list[tuple[int, str, list[str]]] = []
    in_fence = False
    for line in body.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and (m := _HEADING.match(line)):
            out.append((len(m.group(1)), m.group(2), []))
            continue
        if out:
            out[-1][2].append(line)
    return [(lvl, text, "\n".join(lines).strip()) for lvl, text, lines in out]


def body_errors(doc: PlannedDoc, body: str) -> list[str]:
    errors: list[str] = []
    if body.lstrip().startswith("---"):
        errors.append("the body starts with frontmatter; output the body only")
    found = split_sections(body)
    expected = [(s.level, s.anchor) for s in doc.sections]
    got = [(lvl, slugify(text)) for lvl, text, _ in found]
    if got != expected:
        want = ", ".join(
            f"{'#' * lvl} {s.heading}" for s, (lvl, _) in zip(doc.sections, expected, strict=True)
        )
        have = ", ".join(f"{'#' * lvl} {text}" for lvl, text, _ in found) or "none"
        errors.append(f"headings must be exactly [{want}] in that order; got [{have}]")
        return errors  # section checks are meaningless if the sections are wrong
    first_heading = next((i for i, ln in enumerate(body.splitlines()) if _HEADING.match(ln)), 0)
    if any(ln.strip() for ln in body.splitlines()[:first_heading]):
        errors.append("there is text before the first section heading")

    for s, (_, _, text) in zip(doc.sections, found, strict=True):
        lines = text.splitlines()
        numbered = sum(bool(_NUMBERED.match(ln)) for ln in lines)
        has_table = any(_TABLE_RULE.match(ln) for ln in lines)
        has_code = any(_FENCE.match(ln) for ln in lines)
        where = f"section '{s.heading}'"
        if not text:
            errors.append(f"{where} is empty")
        if s.steps:
            need = LONG_PROCEDURE_STEPS if s.steps >= LONG_PROCEDURE_STEPS else 2
            if numbered < need:
                errors.append(f"{where} needs a numbered procedure of {s.steps} steps")
        if s.table and not has_table:
            errors.append(f"{where} needs a Markdown table")
        if not s.table and has_table:
            errors.append(f"{where} must not contain a table")
        if s.code and not has_code:
            errors.append(f"{where} needs a fenced code block")
        if not s.code and has_code:
            errors.append(f"{where} must not contain a code block")
    return errors


def leak_flags(doc: PlannedDoc, body: str, spec: specmod.Spec) -> list[str]:
    """Bold on-screen labels from modules this doc doesn't belong to.

    Bold marks UI instructions, so `**Triggered emails**` in a deals-only doc
    suggests it explains Campaigns to users who may not have Campaigns: a
    content leak the permission filter can't see. Flags are for human review,
    not errors (a bold mention can be a legitimate cross-reference). `core` is
    visible to everyone, so its labels never count.
    """
    # Bold text ending in `.` or `:` is a sentence lead-in ("**Contacts linked
    # to the deal.** Each contact needs..."), not an on-screen label.
    bold = [b for b in re.findall(r"\*\*([^*]+)\*\*", body) if not b.rstrip().endswith((".", ":"))]
    flags = []
    for name, m in spec.modules.items():
        if name in doc.modules or name == specmod.CORE:
            continue
        for label in (*m.ui_labels, m.display_name):
            pattern = re.compile(rf"\b{re.escape(label)}\b")  # labels are capitalised
            if any(pattern.search(b) for b in bold):
                flags.append(f"mentions **{label}** from {name}")
    return sorted(set(flags))


# --- files ------------------------------------------------------------------------------


def render_doc(doc: PlannedDoc, body: str) -> str:
    front = yaml.safe_dump(
        doc.frontmatter(), sort_keys=False, default_flow_style=None, allow_unicode=True
    )
    return f"---\n{front}---\n\n{body.strip()}\n"


def parse_doc(text: str) -> tuple[dict[str, Any], str]:
    m = _FRONTMATTER.match(text)
    if not m:
        raise ValueError("no frontmatter block")
    front = yaml.safe_load(m.group(1))
    if not isinstance(front, dict):
        raise ValueError("frontmatter is not a mapping")
    return front, m.group(2)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"docs": {}}
    raw = yaml.safe_load(path.read_text()) or {}
    raw.setdefault("docs", {})
    return dict(raw)


def save_manifest(manifest: dict[str, Any], plan: DocPlan, path: Path = MANIFEST_PATH) -> None:
    order = {d.doc_id: i for i, d in enumerate(plan.docs)}
    docs = dict(sorted(manifest["docs"].items(), key=lambda kv: order.get(kv[0], len(order))))
    out = {
        "generator": {"plan_version": plan.plan_version, "seed": plan.seed},
        "docs": docs,
    }
    header = (
        "# Provenance of the synthetic docs, written by `make docs-gen`.\n"
        "# sha256 is of the file as generated; a different hash means it was edited by hand.\n"
    )
    path.write_text(header + yaml.safe_dump(out, sort_keys=False, allow_unicode=True))


# --- generating -------------------------------------------------------------------------


@dataclass
class Outcome:
    doc_id: str
    written: bool
    attempts: int = 0
    errors: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    calls: list[Completion] = field(default_factory=list)


async def write_one(
    doc: PlannedDoc, plan: DocPlan, spec: specmod.Spec, prompt: Prompt, client: LLMClient
) -> Outcome:
    messages = build_messages(doc, plan, spec, prompt)
    outcome = Outcome(doc.doc_id, written=False)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        outcome.attempts = attempt
        try:
            completion = await client.complete(messages, role=MODEL_ROLE)
        except LLMError as e:
            outcome.errors = [str(e)]
            return outcome
        outcome.calls.append(completion)
        body = completion.text.strip()
        errors = body_errors(doc, body)
        if not errors:
            text = render_doc(doc, body)
            doc.path.parent.mkdir(parents=True, exist_ok=True)
            doc.path.write_text(text)
            outcome.written, outcome.errors = True, []
            outcome.flags = leak_flags(doc, body, spec)
            return outcome
        outcome.errors = errors
        feedback = "Your document broke these rules:\n" + "\n".join(f"- {e}" for e in errors)
        messages = [
            *messages,
            Message("assistant", completion.text),
            Message("user", feedback + "\nRewrite the whole document, following every rule."),
        ]
    return outcome


async def generate(
    plan: DocPlan,
    spec: specmod.Spec,
    prompt: Prompt,
    client: LLMClient,
    *,
    only: Sequence[str] = (),
    force: bool = False,
    manifest_path: Path = MANIFEST_PATH,
) -> list[Outcome]:
    """Write the selected docs. Existing files are skipped unless `force`."""
    unknown = set(only) - {d.doc_id for d in plan.docs}
    if unknown:
        raise ValueError(f"not in the plan: {sorted(unknown)}")
    todo = [
        d for d in plan.docs if (not only or d.doc_id in only) and (force or not d.path.exists())
    ]
    gate = asyncio.Semaphore(CONCURRENCY)

    async def run(doc: PlannedDoc) -> Outcome:
        async with gate:
            return await write_one(doc, plan, spec, prompt, client)

    outcomes = await asyncio.gather(*(run(d) for d in todo))

    manifest = load_manifest(manifest_path)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    by_id = {d.doc_id: d for d in plan.docs}
    for o in outcomes:
        if not o.written:
            continue
        last = o.calls[-1]
        manifest["docs"][o.doc_id] = {
            "prompt": PROMPT_ID,
            "model_id": last.model_id,
            "provider": last.provider,
            "attempts": o.attempts,
            "input_tokens": sum(c.usage.input_tokens for c in o.calls),
            "output_tokens": sum(c.usage.output_tokens for c in o.calls),
            "generated_at": now,
            "sha256": sha256(by_id[o.doc_id].path.read_text()),
        }
    if any(o.written for o in outcomes):
        save_manifest(manifest, plan, manifest_path)
    return list(outcomes)


# --- checking the corpus ----------------------------------------------------------------


@dataclass
class CorpusReport:
    errors: list[str] = field(default_factory=list)
    flags: dict[str, list[str]] = field(default_factory=dict)
    edited: list[str] = field(default_factory=list)
    present: int = 0
    missing: list[str] = field(default_factory=list)


def check_corpus(
    plan: DocPlan,
    spec: specmod.Spec,
    *,
    docs_dir: Path = DOCS_DIR,
    manifest_path: Path = MANIFEST_PATH,
) -> CorpusReport:
    report = CorpusReport()
    manifest = load_manifest(manifest_path)["docs"]
    planned = {d.path.resolve(): d for d in plan.docs}

    for path in sorted(docs_dir.rglob("*.md")):
        if path.resolve() not in planned:
            report.errors.append(f"{path.relative_to(docs_dir)}: not in the plan")

    for doc in plan.docs:
        if not doc.path.exists():
            report.missing.append(doc.doc_id)
            continue
        report.present += 1
        text = doc.path.read_text()
        where = doc.doc_id
        try:
            front, body = parse_doc(text)
        except ValueError as e:
            report.errors.append(f"{where}: {e}")
            continue
        if front != doc.frontmatter():
            report.errors.append(f"{where}: frontmatter {front} differs from the plan")
        report.errors.extend(f"{where}: {e}" for e in body_errors(doc, body.strip()))
        if flags := leak_flags(doc, body, spec):
            report.flags[where] = flags
        entry = manifest.get(doc.doc_id)
        if entry is None:
            report.errors.append(f"{where}: no MANIFEST.yaml entry")
        elif entry.get("sha256") != sha256(text):
            report.edited.append(where)
    return report


def review_sample(plan: DocPlan, report: CorpusReport, n: int = 10) -> list[str]:
    """Every flagged doc first, then a seeded random pick of the rest, up to n."""
    present = [d.doc_id for d in plan.docs if d.path.exists()]
    flagged = [d for d in present if d in report.flags]
    rest = [d for d in present if d not in report.flags]
    random.Random(plan.seed).shuffle(rest)  # noqa: S311 - review sampling, not security
    return (flagged + rest)[: max(n, len(flagged))]
