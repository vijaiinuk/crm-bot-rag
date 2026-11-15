"""S1.2.1 step C: the generator writes prose; the plan decides structure (no network)."""

import re
from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml
from tools.docgen import PlannedDoc, load_plan, load_spec
from tools.docwriter import (
    body_errors,
    build_messages,
    check_corpus,
    generate,
    leak_flags,
    load_prompt,
    parse_doc,
    render_doc,
    review_sample,
)

from chatbot.ports.llm import Completion, LLMError, Message, Usage
from tools import docgen

SPEC = load_spec()
PLAN = load_plan(spec=SPEC)
PROMPT = load_prompt()
BY_ID = {d.doc_id: d for d in PLAN.docs}


def good_body(doc: PlannedDoc) -> str:
    """A body that satisfies every structural rule for this planned doc."""
    parts = []
    for s in doc.sections:
        parts.append(f"{'#' * s.level} {s.heading}\n\nSome text.")
        if s.steps:
            parts.append("\n".join(f"{i}. Do step {i}." for i in range(1, s.steps + 1)))
        if s.table:
            parts.append("| Field | Meaning |\n|---|---|\n| A | B |")
        if s.code:
            parts.append("```\n#vip\nowner:me\n```")
    return "\n\n".join(parts)


class FakeLLM:
    """Replies in order; or, given a dict, by the doc title in the prompt
    (generation is concurrent, so call order isn't plan order)."""

    def __init__(self, replies: Sequence[str | Exception] | dict[str, list[str]]) -> None:
        self.replies = replies if isinstance(replies, dict) else list(replies)
        self.calls: list[list[Message]] = []

    async def complete(self, messages: Sequence[Message], *, role: str) -> Completion:
        assert role == "docgen"
        self.calls.append(list(messages))
        if isinstance(self.replies, dict):
            title = re.search(r'Write the help document "([^"]+)"', messages[1].content)
            assert title
            reply: str | Exception = self.replies[title.group(1)].pop(0)
        else:
            reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Completion(reply, "vendor/model-1", "Vendor", Usage(100, 50), 10)


@pytest.fixture
def docs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(docgen, "DOCS_DIR", tmp_path)
    return tmp_path


# --- prompt -------------------------------------------------------------------------------


def test_prompt_fills_every_placeholder_from_the_plan() -> None:
    doc = BY_ID["support-sla-policies"]
    system, user = build_messages(doc, PLAN, SPEC, PROMPT)
    assert (system.role, user.role) == ("system", "user")
    assert "$" not in user.content
    assert "SLA policies" in user.content and doc.brief in user.content
    assert (
        "`## Set up an SLA policy` (procedure: a numbered list of about 12 steps)" in user.content
    )
    assert "SLA policies" in user.content, "own module's UI labels are given"
    assert "Collecting e-signatures on quotes" in user.content, "gaps are listed to avoid"


def test_prompt_gives_only_this_docs_modules() -> None:
    _, user = build_messages(BY_ID["deals-stage-automation"], PLAN, SPEC, PROMPT)
    assert "Stage settings" in user.content
    assert "Triggered emails" not in user.content, "other modules' labels are never offered"


def test_prompt_gives_canonical_facts_for_own_modules_only() -> None:
    _, user = build_messages(BY_ID["deals-stage-automation"], PLAN, SPEC, PROMPT)
    assert "A stage can have up to 10 automations" in user.content
    assert "saved as **Paused**" in user.content
    assert "pin up to 20 records" not in user.content, "core facts only go to core docs"
    assert "saved as **Draft**" not in user.content, "no Campaigns facts in a deals-only doc"
    assert "Send triggered email" not in user.content, "no workflow facts in a module doc"


def test_core_docs_get_core_facts() -> None:
    _, user = build_messages(BY_ID["core-navigation"], PLAN, SPEC, PROMPT)
    assert "pin up to 20 records" in user.content


def test_workflow_guide_gets_its_workflow_facts() -> None:
    _, user = build_messages(BY_ID["campaigns-deal-triggers"], PLAN, SPEC, PROMPT)
    assert "**Send triggered email** only when the account has Campaigns" in user.content
    assert "saved as **Draft**" in user.content and "saved as **Paused**" in user.content


def test_workflow_guide_prompt_states_prerequisites() -> None:
    _, user = build_messages(BY_ID["deals-quote-from-deal"], PLAN, SPEC, PROMPT)
    assert "products in a price book" in user.content
    assert "Deals" in user.content and "Quotes" in user.content and "Products" in user.content


# --- body rules ---------------------------------------------------------------------------


def test_good_body_passes() -> None:
    for doc in PLAN.docs:
        assert body_errors(doc, good_body(doc)) == [], doc.doc_id


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda b: b.replace("## Actions", "## Adding actions"), "headings must be exactly"),
        (lambda b: b + "\n\n## Troubleshooting\n\nMore.", "headings must be exactly"),
        (lambda b: b.replace("## Actions", "### Actions"), "headings must be exactly"),
        (lambda b: "# Automating deal stage changes\n\n" + b, "headings must be exactly"),
        (lambda b: "---\ndoc_id: x\n---\n" + b, "frontmatter"),
        (lambda b: "Intro text.\n\n" + b, "text before the first section heading"),
        (lambda b: re.sub(r"^\d+\. .*\n?", "", b, flags=re.M), "numbered procedure"),
        (lambda b: b + "\n\n| a | b |\n|---|---|\n| 1 | 2 |", "must not contain a table"),
        (lambda b: b + "\n\n```\ncode\n```", "must not contain a code block"),
    ],
    ids=[
        "renamed",
        "extra",
        "wrong-level",
        "h1",
        "frontmatter",
        "preamble",
        "no-steps",
        "stray-table",
        "stray-code",
    ],
)
def test_bad_body_is_rejected(mutate: object, reason: str) -> None:
    doc = BY_ID["deals-stage-automation"]
    body = mutate(good_body(doc))  # type: ignore[operator]
    assert any(reason in e for e in body_errors(doc, body)), body_errors(doc, body)


def test_long_procedure_needs_all_its_steps() -> None:
    doc = BY_ID["support-sla-policies"]
    short = good_body(doc).replace("\n".join(f"{i}. Do step {i}." for i in range(5, 13)), "")
    assert any("12 steps" in e for e in body_errors(doc, short))


def test_missing_table_and_code_are_rejected() -> None:
    table_doc, code_doc = BY_ID["contacts-custom-fields"], BY_ID["core-search-tips"]
    no_table = good_body(table_doc).replace("| Field | Meaning |\n|---|---|\n| A | B |", "")
    no_code = good_body(code_doc).replace("```\n#vip\nowner:me\n```", "")
    assert any("needs a Markdown table" in e for e in body_errors(table_doc, no_table))
    assert any("needs a fenced code block" in e for e in body_errors(code_doc, no_code))


def test_hash_lines_in_code_are_not_headings() -> None:
    doc = BY_ID["core-search-tips"]
    assert "#vip" in good_body(doc)
    assert body_errors(doc, good_body(doc)) == []


# --- leak lint ----------------------------------------------------------------------------


def test_other_modules_bold_labels_are_flagged() -> None:
    doc = BY_ID["deals-stage-automation"]
    body = good_body(doc) + "\n\nThen open **Triggered emails** and pick a template."
    assert leak_flags(doc, body, SPEC) == ["mentions **Triggered emails** from campaigns"]


def test_sentence_lead_ins_and_lowercase_words_are_not_flagged() -> None:
    doc = BY_ID["campaigns-deal-triggers"]
    body = (
        good_body(doc)
        + "\n\n- **Contacts linked to the deal.** Each needs an email.\n"
        + "Send to **All contacts on the deal**.\n- **Reports:** see below."
    )
    assert leak_flags(doc, body, SPEC) == []


def test_own_and_core_labels_are_not_flagged() -> None:
    doc = BY_ID["deals-stage-automation"]
    body = good_body(doc) + "\n\nGo to **Deals → Stage settings**, or **Home**. Plain Campaigns."
    assert leak_flags(doc, body, SPEC) == []


# --- files --------------------------------------------------------------------------------


def test_render_writes_plan_frontmatter_and_round_trips() -> None:
    doc = BY_ID["deals-forecasting"]
    text = render_doc(doc, good_body(doc))
    assert text.startswith(
        "---\ndoc_id: deals-forecasting\ntitle: Forecasting deals\n"
        "modules: [deals, reports]\nversion: 1\n---\n\n## Forecast categories"
    )
    front, body = parse_doc(text)
    assert front == doc.frontmatter()
    assert body_errors(doc, body.strip()) == []


# --- generating ---------------------------------------------------------------------------


async def test_generate_writes_doc_and_manifest(docs_dir: Path) -> None:
    doc = BY_ID["deals-stage-automation"]
    llm = FakeLLM([good_body(doc)])
    manifest = docs_dir / "MANIFEST.yaml"
    (o,) = await generate(PLAN, SPEC, PROMPT, llm, only=[doc.doc_id], manifest_path=manifest)
    assert o.written and o.attempts == 1
    front, _ = parse_doc((docs_dir / "deals" / "deals-stage-automation.md").read_text())
    assert front["modules"] == ["deals"]
    entry = yaml.safe_load(manifest.read_text())["docs"]["deals-stage-automation"]
    assert entry["model_id"] == "vendor/model-1" and entry["input_tokens"] == 100
    assert entry["prompt"] == "docgen_v3", "recorded per doc, so mixed versions stay traceable"


async def test_model_frontmatter_is_never_used(docs_dir: Path) -> None:
    """Rule 4: a reply that tags itself with more modules is rejected, then retried."""
    doc = BY_ID["deals-stage-automation"]
    sneaky = "---\nmodules: [core]\n---\n" + good_body(doc)
    llm = FakeLLM([sneaky, good_body(doc)])
    (o,) = await generate(
        PLAN, SPEC, PROMPT, llm, only=[doc.doc_id], manifest_path=docs_dir / "m.yaml"
    )
    assert o.written and o.attempts == 2
    feedback = llm.calls[1][-1].content
    assert "frontmatter" in feedback and "Rewrite the whole document" in feedback
    front, _ = parse_doc(doc.path.read_text())
    assert front["modules"] == ["deals"]


async def test_doc_that_fails_twice_is_not_written(docs_dir: Path) -> None:
    doc = BY_ID["deals-stage-automation"]
    bad = good_body(doc).replace("## Actions", "## Something else")
    llm = FakeLLM([bad, bad])
    (o,) = await generate(
        PLAN, SPEC, PROMPT, llm, only=[doc.doc_id], manifest_path=docs_dir / "m.yaml"
    )
    assert not o.written and o.attempts == 2
    assert not doc.path.exists()
    assert not (docs_dir / "m.yaml").exists()


async def test_llm_error_is_reported_not_raised(docs_dir: Path) -> None:
    doc = BY_ID["deals-stage-automation"]
    llm = FakeLLM([LLMError("rate limited")])
    (o,) = await generate(
        PLAN, SPEC, PROMPT, llm, only=[doc.doc_id], manifest_path=docs_dir / "m.yaml"
    )
    assert not o.written and o.errors == ["rate limited"]


async def test_existing_docs_are_skipped_unless_forced(docs_dir: Path) -> None:
    doc = BY_ID["deals-stage-automation"]
    m = docs_dir / "m.yaml"
    await generate(
        PLAN, SPEC, PROMPT, FakeLLM([good_body(doc)]), only=[doc.doc_id], manifest_path=m
    )
    llm = FakeLLM([good_body(doc)])
    assert await generate(PLAN, SPEC, PROMPT, llm, only=[doc.doc_id], manifest_path=m) == []
    (o,) = await generate(PLAN, SPEC, PROMPT, llm, only=[doc.doc_id], force=True, manifest_path=m)
    assert o.written


async def test_unknown_doc_id_is_refused() -> None:
    with pytest.raises(ValueError, match="not in the plan"):
        await generate(PLAN, SPEC, PROMPT, FakeLLM([]), only=["no-such-doc"])


# --- checking the corpus ------------------------------------------------------------------


async def write_corpus(docs_dir: Path, *doc_ids: str) -> Path:
    m = docs_dir / "MANIFEST.yaml"
    llm = FakeLLM({BY_ID[d].title: [good_body(BY_ID[d])] for d in doc_ids})
    await generate(PLAN, SPEC, PROMPT, llm, only=list(doc_ids), manifest_path=m)
    return m


async def test_clean_corpus_has_no_errors(docs_dir: Path) -> None:
    m = await write_corpus(docs_dir, "deals-stage-automation", "core-search-tips")
    report = check_corpus(PLAN, SPEC, docs_dir=docs_dir, manifest_path=m)
    assert report.errors == [] and report.present == 2 and len(report.missing) == 40


async def test_tampered_modules_are_an_error(docs_dir: Path) -> None:
    m = await write_corpus(docs_dir, "deals-stage-automation")
    path = BY_ID["deals-stage-automation"].path
    path.write_text(path.read_text().replace("modules: [deals]", "modules: [core]"))
    report = check_corpus(PLAN, SPEC, docs_dir=docs_dir, manifest_path=m)
    assert any("differs from the plan" in e for e in report.errors)
    assert report.edited == ["deals-stage-automation"]


async def test_unplanned_doc_is_an_error(docs_dir: Path) -> None:
    m = await write_corpus(docs_dir, "deals-stage-automation")
    (docs_dir / "deals" / "stray.md").write_text("---\ndoc_id: stray\n---\n")
    report = check_corpus(PLAN, SPEC, docs_dir=docs_dir, manifest_path=m)
    assert any("stray.md: not in the plan" in e for e in report.errors)


async def test_review_sample_puts_flagged_docs_first(docs_dir: Path) -> None:
    doc = BY_ID["deals-stage-automation"]
    m = docs_dir / "MANIFEST.yaml"
    leaky = good_body(doc) + "\n\nOpen **Audiences**."
    others = ["deals-records", "deals-board-view"]
    replies = {doc.title: [leaky], **{BY_ID[d].title: [good_body(BY_ID[d])] for d in others}}
    await generate(
        PLAN, SPEC, PROMPT, FakeLLM(replies), only=[doc.doc_id, *others], manifest_path=m
    )
    report = check_corpus(PLAN, SPEC, docs_dir=docs_dir, manifest_path=m)
    sample = review_sample(PLAN, report, n=2)
    assert sample[0] == "deals-stage-automation" and len(sample) == 2
