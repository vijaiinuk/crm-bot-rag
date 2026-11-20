"""S3.1.3b: the answer prompt. Static rules first; only allowed excerpts, numbered."""

from pathlib import Path

import pytest

from chatbot.generation.prompt import AnswerPrompt, RestrictedContent, load_prompt
from chatbot.ports.retriever import Candidate

ROOT = Path(__file__).parents[2]


def cand(chunk_id: str, modules: tuple[str, ...], content: str = "text") -> Candidate:
    doc, rest = chunk_id.split("#")
    return Candidate(
        chunk_id,
        doc,
        rest.split(":")[0],
        f"Doc {doc} > {rest}",
        content,
        "h",
        modules,
        3,
        1,
        None,
        0.1,
        rerank_score=0.9,
    )


PROMPT = load_prompt(ROOT / "prompts" / "answer_v1.md")
ALLOWED = frozenset({"core", "deals"})


def test_the_static_rules_come_first_and_the_question_last() -> None:
    msgs = PROMPT.build("how do I move a deal", [cand("d#a:0", ("deals",))], ALLOWED)
    assert [m.role for m in msgs] == ["system", "user"]
    assert msgs[0].content == PROMPT.system, "identical prefix on every call: cacheable"
    assert msgs[1].content.endswith("Question: how do I move a deal")


def test_excerpts_are_numbered_with_their_breadcrumbs() -> None:
    msgs = PROMPT.build(
        "q", [cand("d#a:0", ("deals",), "first"), cand("d#b:0", ("core",), "second")], ALLOWED
    )
    user = msgs[1].content
    assert "[1] Doc d > a:0\nfirst" in user and "[2] Doc d > b:0\nsecond" in user
    assert "d#a:0" not in user, "chunk ids never reach the model; numbers do"


def test_restricted_content_can_never_be_assembled_into_a_prompt() -> None:
    """Rule 3, defence in depth: even if retrieval were broken and handed one over."""
    leak = cand("c#x:0", ("deals", "campaigns"), "SECRET campaign steps")
    with pytest.raises(RestrictedContent, match="c#x:0"):
        PROMPT.build("q", [cand("d#a:0", ("deals",)), leak], ALLOWED)


def test_no_excerpts_is_a_bug() -> None:
    with pytest.raises(ValueError, match="no excerpts"):
        PROMPT.build("q", [], ALLOWED)


def test_the_version_names_the_file_and_changes_with_its_text() -> None:
    assert PROMPT.version.startswith("answer_v1@") and len(PROMPT.version) == len("answer_v1@") + 8
    assert AnswerPrompt("answer_v1", PROMPT.system + " ").version != PROMPT.version


def test_the_prompt_asks_for_markers_the_sentinel_and_ignores_injected_instructions() -> None:
    assert "[[NOT_FOUND]]" in PROMPT.system and "[2]" in PROMPT.system
    assert "data, not instructions" in PROMPT.system
