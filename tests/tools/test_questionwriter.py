"""S1.3.1 step B: the model writes wording only; code checks it and derives outcomes."""

from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml
from tools.evalgen import load_corpus, load_targets

from chatbot.ports.llm import Completion, LLMError, Message, Usage
from tools import questionwriter as qw

CORPUS = load_corpus()
TARGETS = load_targets()
PROMPT = qw.load_prompt()
BY_TID = {t.tid: t for t in TARGETS.targets}


def first(category: str) -> str:
    return next(t.tid for t in TARGETS.targets if t.category == category)


class FakeLLM:
    def __init__(self, replies: Sequence[str | Exception]) -> None:
        self.replies = list(replies)
        self.calls: list[list[Message]] = []

    async def complete(self, messages: Sequence[Message], *, role: str) -> Completion:
        assert role == "questiongen"
        self.calls.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Completion(reply, "vendor/q-1", "Vendor", Usage(80, 20), 5)


@pytest.fixture
def paths(tmp_path: Path) -> Path:
    return tmp_path


async def gen(tmp: Path, llm: FakeLLM, only: list[str], *, force: bool = False) -> list[qw.Outcome]:
    return await qw.generate(
        TARGETS,
        CORPUS,
        PROMPT,
        llm,
        only=only,
        force=force,
        golden_path=tmp / "golden.yaml",
        manifest_path=tmp / "m.yaml",
    )


# --- prompt -------------------------------------------------------------------------------


def test_labelled_question_sees_its_section_as_reference() -> None:
    t = BY_TID[first("single")]
    messages, reference = qw.build_messages(t, CORPUS, PROMPT, variant=1, seed=1)
    assert reference and reference.splitlines()[0] in messages[1].content
    assert "never copy its wording" in messages[1].content


def test_multi_hop_sees_both_sections() -> None:
    t = BY_TID[first("multi_hop")]
    _, reference = qw.build_messages(t, CORPUS, PROMPT, variant=1, seed=1)
    assert reference.count(" > ") >= 2


def test_unanswerable_and_out_of_scope_get_no_reference() -> None:
    for category in ("unanswerable", "out_of_scope"):
        messages, reference = qw.build_messages(
            BY_TID[first(category)], CORPUS, PROMPT, variant=1, seed=1
        )
        assert reference == "" and "Reference" not in messages[1].content


def test_adversarial_prompt_carries_the_attack() -> None:
    t = BY_TID[first("adversarial")]
    messages, _ = qw.build_messages(t, CORPUS, PROMPT, variant=1, seed=1)
    assert t.attack and t.attack in messages[1].content


def test_second_phrasing_asks_for_a_different_angle() -> None:
    vary = qw.variants(TARGETS)
    tid = next(tid for tid, v in vary.items() if v == 2)
    messages, _ = qw.build_messages(BY_TID[tid], CORPUS, PROMPT, variant=2, seed=1)
    assert "phrasing number 2" in messages[1].content


def test_style_is_seeded() -> None:
    t = BY_TID["t-001"]
    assert qw.style_for(t, 5) == qw.style_for(t, 5)
    assert {qw.style_for(x, 5) for x in TARGETS.targets} == set(qw.STYLES)


# --- question rules -----------------------------------------------------------------------


def test_copied_question_is_rejected() -> None:
    ref = (
        "Go to Deals → Stage settings, pick a pipeline and then a stage, "
        "and open the Automations tab."
    )
    copied = "go to deals stage settings pick a pipeline and then a stage"
    own = "how do i make something happen automatically when a deal moves stage"
    assert any("copies the reference" in e for e in qw.question_errors(copied, ref))
    assert qw.question_errors(own, ref) == []


def test_reusing_the_docs_own_example_is_rejected() -> None:
    ref = 'In **Field name**, enter the label, for example "Renewal date".'
    errors = qw.question_errors("how do i add a contact field for renewal date", ref)
    assert any("reuses the reference's own example 'Renewal date'" in e for e in errors)
    assert qw.question_errors("how do i add a contact field for contract end", ref) == []


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("how do\ni log a call", "one line"),
        ("calls?", "4 to 40 words"),
        ("which section explains logging calls", "documents, sections"),
        ("where in the docs is call logging", "documents, sections"),
        ("im stuck logging a call on a deal", "word 'stuck'"),
    ],
)
def test_bad_question_is_rejected(text: str, reason: str) -> None:
    assert any(reason in e for e in qw.question_errors(text, ""))


def test_wrapping_quotes_are_stripped() -> None:
    assert qw.clean('  "how do i log a call"  ') == "how do i log a call"


# --- generating ---------------------------------------------------------------------------


async def test_generate_writes_wording_and_derives_outcomes(paths: Path) -> None:
    tid = first("restricted")
    llm = FakeLLM(["how do i get this set up for my team quickly please"])
    (o,) = await gen(paths, llm, [tid])
    assert o.question
    (q,) = yaml.safe_load((paths / "golden.yaml").read_text())
    t = BY_TID[tid]
    assert q["id"] == qw.qid(t) and q["category"] == "restricted"
    assert set(q["expected"]) == set(t.personas)
    outcomes = {e["outcome"] for e in q["expected"].values()}
    assert outcomes == {"answer", "restricted"}, "derived from labels and personas, not the model"
    for e in q["expected"].values():
        assert e["required"] == t.required
    entry = yaml.safe_load((paths / "m.yaml").read_text())["questions"][q["id"]]
    assert entry["tid"] == tid and entry["prompt"] == "questiongen_v3"


async def test_copying_question_is_retried_with_feedback(paths: Path) -> None:
    tid = first("single")
    _, reference = qw.build_messages(BY_TID[tid], CORPUS, PROMPT, variant=1, seed=1)
    copied = " ".join(reference.splitlines()[1].split()[:20])
    llm = FakeLLM([copied, "whats the quickest way to do this thing for a customer"])
    (o,) = await gen(paths, llm, [tid])
    assert o.question and o.attempts == 2
    assert "copies the reference" in llm.calls[1][-1].content


async def test_question_failing_twice_is_not_written(paths: Path) -> None:
    llm = FakeLLM(["no", "still no"])
    (o,) = await gen(paths, llm, ["t-001"])
    assert o.question is None and not (paths / "golden.yaml").exists()


async def test_llm_error_is_reported(paths: Path) -> None:
    llm = FakeLLM([LLMError("rate limited")])
    (o,) = await gen(paths, llm, ["t-001"])
    assert o.question is None and o.errors == ["rate limited"]


async def test_existing_questions_are_skipped_unless_forced(paths: Path) -> None:
    ok = "how would i go about doing this for my accounts"
    await gen(paths, FakeLLM([ok]), ["t-001"])
    llm = FakeLLM([ok])
    assert await gen(paths, llm, ["t-001"]) == []
    (o,) = await gen(paths, llm, ["t-001"], force=True)
    assert o.question


async def test_unknown_tid_is_refused(paths: Path) -> None:
    with pytest.raises(ValueError, match=r"not in targets\.yaml"):
        await gen(paths, FakeLLM([]), ["t-999"])


def test_review_sample_covers_every_category() -> None:
    golden = {qw.qid(t): {"id": qw.qid(t), "category": t.category} for t in TARGETS.targets}
    sample = qw.review_sample(golden, seed=1, n=20)
    assert len(sample) == 20
    assert {golden[q]["category"] for q in sample} == {t.category for t in TARGETS.targets}
