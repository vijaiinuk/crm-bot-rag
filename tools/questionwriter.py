"""Writes the wording of synthetic eval questions with an LLM.

Each target (evals/synthetic/targets.yaml) already fixes the category, the
required labels and the personas. The model writes one question; code checks
it, derives every persona's expected outcome, and writes the golden file.
"""

import asyncio
import random
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from string import Template
from typing import Any

import yaml

from chatbot.evals.golden import GoldenQuestion, expected_for, split_label
from chatbot.ports.llm import Completion, LLMClient, LLMError, Message
from tools import docgen
from tools.docwriter import parse_doc, split_sections
from tools.evalgen import GOLDEN_DIR, SYNTHETIC_DIR, Corpus, Target, Targets

PROMPT_ID = "questiongen_v3"
PROMPT_PATH = docgen.ROOT / "prompts" / f"{PROMPT_ID}.md"
GOLDEN_PATH = GOLDEN_DIR / "synthetic_v1.yaml"
MANIFEST_PATH = SYNTHETIC_DIR / "MANIFEST.yaml"
MODEL_ROLE = "questiongen"
MAX_ATTEMPTS = 2
CONCURRENCY = 4
MIN_WORDS, MAX_WORDS = 4, 40
# Share of the question's 4-word sequences that may also appear in its
# reference text. Above this, it echoes the docs and flatters keyword search.
MAX_COPY = 0.34

STYLES = (
    "short and casual, all lowercase, no question mark",
    "one full, polite sentence",
    "terse, like a search query of 4 to 8 words",
    "a bit frustrated: something isn't working the way they expected (never use the word 'stuck')",
    "adds a short, realistic reason in a few words, only if it fits naturally",
)
# Style hints are part of the prompt: changing them means a new PROMPT_ID.
# v1 pilot: "frustrated" made most questions say "i'm stuck", and "mentions why
# they need it" forced filler like "a customer is waiting".
_FORBIDDEN = re.compile(r"\b(documents?|documentation|docs|sections?|headings?|anchors?)\b", re.I)
_WORD = re.compile(r"[a-z0-9']+")


# --- prompt -------------------------------------------------------------------------------


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
    return Prompt(
        Template("\n".join(parts["system"]).strip()), Template("\n".join(parts["user"]).strip())
    )


def section_text(label: str, corpus: Corpus) -> str:
    doc_id, anchor = split_label(label)
    path = next(docgen.DOCS_DIR.rglob(f"{doc_id}.md"))
    _, body = parse_doc(path.read_text())
    for _, heading, text in split_sections(body):
        if corpus.headings[doc_id].get(anchor) == heading:
            return f"{corpus.titles[doc_id]} > {heading}\n{text}"
    raise ValueError(f"{label}: section not found")


def variants(targets: Targets) -> dict[str, int]:
    """1 for the first target with a given topic, 2 for the next, and so on."""
    seen: Counter[tuple[Any, ...]] = Counter()
    out = {}
    for t in targets.targets:
        key = (t.category, tuple(t.required), t.gap, t.hint, t.attack)
        seen[key] += 1
        out[t.tid] = seen[key]
    return out


def style_for(t: Target, seed: int) -> str:
    return random.Random(f"{seed}:{t.tid}").choice(STYLES)  # noqa: S311 - variety, not security


def build_messages(
    t: Target, corpus: Corpus, prompt: Prompt, *, variant: int, seed: int
) -> tuple[list[Message], str]:
    """The messages, and the reference text the copy check compares against."""
    references = [section_text(label, corpus) for label in t.required]
    if t.category == "multi_hop":
        task = (
            f"Write one question about this goal: {t.hint}. Answering it fully takes steps "
            "from both parts of the product help below, so the question must need both."
        )
    elif t.category == "adversarial":
        task = (
            "The user wants help with something their company may not have licensed for "
            f"them. Write their question about this: {t.hint}. How they try to get around "
            f"it: {t.attack}."
        )
    elif t.category == "unanswerable":
        task = (
            f"Write a question asking how to do this in the CRM: {t.hint}. The product help "
            "doesn't cover it; don't hint at that."
        )
    elif t.category == "out_of_scope":
        task = (
            "Write a message someone types into the CRM's help chat that is not about "
            f"using the CRM at all. It is about: {t.hint}."
        )
    else:  # single, restricted
        task = f"Write a question that this part of the product help answers: {t.hint}."
    if variant > 1:
        task += (
            f" This is phrasing number {variant} of the same topic: take a different angle "
            "from the obvious how-to question, for example the problem they have or the "
            "result they want."
        )
    reference = "\n\n".join(references)
    shown = (
        f"Reference (to make sure the question fits; never copy its wording):\n{reference}"
        if reference
        else ""
    )
    user = prompt.user.substitute(task=task, style=style_for(t, seed), reference=shown)
    return [Message("system", prompt.system.substitute()), Message("user", user)], reference


# --- checking a question ------------------------------------------------------------------


def clean(text: str) -> str:
    q = text.strip()
    if len(q) >= 2 and q[0] == q[-1] and q[0] in "\"'":
        q = q[1:-1].strip()
    return q


def _grams(text: str, n: int = 4) -> set[tuple[str, ...]]:
    words = _WORD.findall(text.lower())
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def copy_ratio(question: str, reference: str) -> float:
    q = _grams(question)
    return len(q & _grams(reference)) / len(q) if q else 0.0


def examples_in(reference: str) -> list[str]:
    """Sample names the docs invented, written in quotes ("Renewal date").

    The 4-word copy check misses these because they're short. Unquoted
    examples ("such as Billing") are left to review: matching them by code
    would also catch ordinary words.
    """
    return [e for e in re.findall(r'"([^"\n]{3,40})"', reference) if not e.startswith("{{")]


def question_errors(question: str, reference: str) -> list[str]:
    errors = []
    if "\n" in question:
        errors.append("output exactly one line")
    words = len(question.split())
    if not MIN_WORDS <= words <= MAX_WORDS:
        errors.append(f"use {MIN_WORDS} to {MAX_WORDS} words (got {words})")
    if re.search(r"\bstuck\b", question, re.I):
        errors.append("don't use the word 'stuck'; describe what isn't working")
    if _FORBIDDEN.search(question):
        errors.append("don't mention documents, sections, headings or the docs")
    borrowed = [e for e in examples_in(reference) if e.lower() in question.lower()]
    if borrowed:
        errors.append(
            f"it reuses the reference's own example {borrowed[0]!r}; a real user wouldn't "
            "know it, so use their own name or value, or leave it out"
        )
    if reference and (ratio := copy_ratio(question, reference)) > MAX_COPY:
        errors.append(
            f"it copies the reference wording ({ratio:.0%} of its 4-word phrases); "
            "say it the way a user would"
        )
    return errors


# --- generating ---------------------------------------------------------------------------


@dataclass
class Outcome:
    tid: str
    question: str | None = None
    attempts: int = 0
    errors: list[str] = field(default_factory=list)
    calls: list[Completion] = field(default_factory=list)
    copy: float = 0.0


async def write_one(
    t: Target, corpus: Corpus, prompt: Prompt, client: LLMClient, *, variant: int, seed: int
) -> Outcome:
    messages, reference = build_messages(t, corpus, prompt, variant=variant, seed=seed)
    outcome = Outcome(t.tid)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        outcome.attempts = attempt
        try:
            completion = await client.complete(messages, role=MODEL_ROLE)
        except LLMError as e:
            outcome.errors = [str(e)]
            return outcome
        outcome.calls.append(completion)
        question = clean(completion.text)
        errors = question_errors(question, reference)
        if not errors:
            outcome.question, outcome.errors = question, []
            outcome.copy = round(copy_ratio(question, reference), 2)
            return outcome
        outcome.errors = errors
        messages = [
            *messages,
            Message("assistant", completion.text),
            Message("user", "That broke these rules:\n- " + "\n- ".join(errors) + "\nTry again."),
        ]
    return outcome


def qid(t: Target) -> str:
    return "q-" + t.tid.removeprefix("t-").zfill(4)


def to_golden(t: Target, question: str, corpus: Corpus) -> dict[str, Any]:
    """The golden entry: wording from the model, everything else from code."""
    expected = {
        p: expected_for(t.category, t.required, corpus.personas[p], corpus.doc_modules)
        for p in t.personas
    }
    q = GoldenQuestion(id=qid(t), question=question, category=t.category, expected=expected)
    return q.model_dump(exclude_defaults=True)


def load_golden(path: Path = GOLDEN_PATH) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    return {q["id"]: q for q in (yaml.safe_load(path.read_text()) or [])}


def save_golden(questions: dict[str, dict[str, Any]], path: Path = GOLDEN_PATH) -> None:
    header = (
        "# Synthetic golden eval questions (S1.3.1), written by `make evals-gen`.\n"
        "# Wording by the `questiongen` model; labels, personas and expected outcomes by\n"
        "# code (evals/synthetic/targets.yaml, chatbot.evals.golden). Provenance:\n"
        "# evals/synthetic/MANIFEST.yaml. Hand edits to wording are fine; outcomes are\n"
        "# re-derived by `make evals-check`.\n"
    )
    ordered = [questions[k] for k in sorted(questions)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        header + yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True, width=100)
    )


async def generate(
    targets: Targets,
    corpus: Corpus,
    prompt: Prompt,
    client: LLMClient,
    *,
    only: Sequence[str] = (),
    force: bool = False,
    golden_path: Path = GOLDEN_PATH,
    manifest_path: Path = MANIFEST_PATH,
) -> list[Outcome]:
    unknown = set(only) - {t.tid for t in targets.targets}
    if unknown:
        raise ValueError(f"not in targets.yaml: {sorted(unknown)}")
    golden = load_golden(golden_path)
    todo = [
        t
        for t in targets.targets
        if (not only or t.tid in only) and (force or qid(t) not in golden)
    ]
    vary = variants(targets)
    gate = asyncio.Semaphore(CONCURRENCY)

    async def run(t: Target) -> Outcome:
        async with gate:
            return await write_one(
                t, corpus, prompt, client, variant=vary[t.tid], seed=targets.seed
            )

    outcomes = await asyncio.gather(*(run(t) for t in todo))

    by_tid = {t.tid: t for t in targets.targets}
    manifest: dict[str, Any] = (
        yaml.safe_load(manifest_path.read_text()) if manifest_path.exists() else {}
    ) or {}
    entries: dict[str, Any] = manifest.get("questions", {})
    now = datetime.now(UTC).isoformat(timespec="seconds")
    for o in outcomes:
        if o.question is None:
            continue
        t = by_tid[o.tid]
        golden[qid(t)] = to_golden(t, o.question, corpus)
        last = o.calls[-1]
        entries[qid(t)] = {
            "tid": t.tid,
            "prompt": PROMPT_ID,
            "model_id": last.model_id,
            "provider": last.provider,
            "attempts": o.attempts,
            "input_tokens": sum(c.usage.input_tokens for c in o.calls),
            "output_tokens": sum(c.usage.output_tokens for c in o.calls),
            "copy_ratio": o.copy,
            "generated_at": now,
        }
    if any(o.question for o in outcomes):
        save_golden(golden, golden_path)
        out = {
            "generator": {"seed": targets.seed, "seed_version": targets.seed_version},
            "questions": dict(sorted(entries.items())),
        }
        manifest_path.write_text(
            "# Provenance of evals/golden/synthetic_v1.yaml, written by `make evals-gen`.\n"
            + yaml.safe_dump(out, sort_keys=False)
        )
    return list(outcomes)


def review_sample(golden: dict[str, dict[str, Any]], seed: int, n: int = 20) -> list[str]:
    """At least one per category, then a seeded pick of the rest, up to n."""
    rng = random.Random(seed)  # noqa: S311 - review sampling, not security
    by_cat: dict[str, list[str]] = {}
    for q in golden.values():
        by_cat.setdefault(q["category"], []).append(q["id"])
    picked = []
    for ids in by_cat.values():
        picked.append(rng.choice(sorted(ids)))
    rest = sorted(set(golden) - set(picked))
    rng.shuffle(rest)
    return sorted(picked + rest[: max(0, n - len(picked))])
