"""S2.1.1: fail-closed validation. Untagged or mis-tagged docs abort the whole run."""

from pathlib import Path

import pytest

from chatbot.ingest.validate import (
    MAX_BYTES,
    DocValidator,
    IngestAborted,
    load_frontmatter_schema,
)

ROOT = Path(__file__).parents[2]
SCHEMA = load_frontmatter_schema(ROOT / "data" / "spec" / "doc_frontmatter.schema.json")
KNOWN = frozenset({"core", "contacts", "deals", "campaigns", "reports"})
V = DocValidator(KNOWN, SCHEMA)

FRONT = (
    "---\ndoc_id: deals-stage-automation\ntitle: Automating deal stage changes\n"
    "modules: [deals]\nversion: 1\n---\n"
)
BODY = (
    "## Triggers\n\nWhen a deal enters a stage.\n\n### Advanced\n\nMore.\n\n"
    "## Actions\n\n1. Add one.\n"
)


def doc(front: str = FRONT, body: str = BODY) -> bytes:
    return (front + "\n" + body).encode()


def errors(raw: bytes) -> str:
    return "\n".join(V.validate_doc(raw, source="x.md").errors)


# --- a valid doc ----------------------------------------------------------------------------


def test_valid_doc_carries_frontmatter_and_anchors() -> None:
    report = V.validate_doc(doc(), source="deals/x.md")
    assert report.errors == []
    d = report.doc
    assert d is not None
    assert (d.doc_id, d.title, d.modules, d.version) == (
        "deals-stage-automation",
        "Automating deal stage changes",
        ("deals",),
        1,
    )
    assert [h.anchor for h in d.headings] == ["triggers", "advanced", "actions"]
    assert d.source == "deals/x.md" and len(d.sha256) == 64


def test_hash_lines_inside_code_blocks_are_not_headings() -> None:
    body = "## Search operators\n\n```\n# not a heading\n#vip\n```\n"
    assert errors(doc(body=body)) == ""


# --- frontmatter: fail closed ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("front", "reason"),
    [
        (FRONT.replace("modules: [deals]\n", ""), "'modules' is a required property"),
        (FRONT.replace("[deals]", "[]"), "modules"),
        (FRONT.replace("[deals]", "[dealz]"), "unknown module 'dealz'"),
        (FRONT.replace("[deals]", "[deals, dealz]"), "unknown module 'dealz'"),
        (FRONT.replace("[deals]", "[deals, deals]"), "non-unique"),
        (FRONT.replace("version: 1\n", ""), "'version' is a required property"),
        (FRONT.replace("title: Automating deal stage changes\n", ""), "'title'"),
        (FRONT.replace("deals-stage-automation", "Deals Stage"), "does not match"),
        (FRONT.replace("version: 1\n", "version: 1\naudience: admins\n"), "Additional properties"),
        (FRONT.replace("version: 1\n", "version: 1\nmodules: [core]\n"), "duplicate key 'modules'"),
        ("---\n[unclosed\n---\n", "frontmatter is not valid YAML"),
        ("---\n- a\n- b\n---\n", "frontmatter must be a mapping"),
        ("", "missing frontmatter"),
    ],
    ids=[
        "untagged",
        "empty-modules",
        "unknown-module",
        "one-unknown-module",
        "repeated-module",
        "no-version",
        "no-title",
        "bad-doc-id",
        "extra-field",
        "duplicate-key",
        "bad-yaml",
        "not-a-mapping",
        "no-frontmatter",
    ],
)
def test_bad_frontmatter_is_rejected(front: str, reason: str) -> None:
    report = V.validate_doc(doc(front=front), source="x.md")
    assert report.doc is None
    assert any(reason in e for e in report.errors), report.errors


def test_doc_id_is_reported_even_when_the_doc_is_invalid() -> None:
    """The admin app attaches a rejected upload to its doc_id."""
    report = V.validate_doc(doc(front=FRONT.replace("[deals]", "[dealz]")), source="x.md")
    assert report.doc is None and report.doc_id == "deals-stage-automation"


def test_not_utf8_and_too_big_are_rejected() -> None:
    assert "not valid UTF-8" in errors(b"\xff\xfe" + doc())
    assert "larger than" in errors(doc() + b"a" * MAX_BYTES)


# --- body: anything the chunker or anchors would get wrong ----------------------------------


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("# Automating deal stage changes\n\n## Triggers\n\nx\n", "level-1 heading"),
        ("Triggers\n========\n\nx\n", "underlined (setext) heading"),
        ("## Triggers\n\nIntro\n---\n\nx\n", "underlined (setext) heading"),
        ("## Triggers\n\n```\ncode with no end\n\n## Actions\n", "unclosed code block"),
        ("### Triggers\n\nx\n", "first heading must be level 2"),
        ("## Triggers\n\n#### Deep\n\nx\n", "skips from level 2 to level 4"),
        ("## Triggers\n\nx\n\n## Triggers!\n\ny\n", "duplicate anchor 'triggers'"),
        ("## !!!\n\nx\n", "has no letters or digits"),
        ("Just some text, no sections.\n", "at least one ## section"),
    ],
    ids=[
        "h1",
        "setext-equals",
        "setext-dashes",
        "unclosed-fence",
        "starts-at-h3",
        "skips-level",
        "duplicate-anchor",
        "empty-anchor",
        "no-headings",
    ],
)
def test_bad_body_is_rejected(body: str, reason: str) -> None:
    assert reason in errors(doc(body=body))


def test_a_horizontal_rule_after_a_blank_line_is_fine() -> None:
    assert errors(doc(body="## Triggers\n\nx\n\n---\n\ny\n")) == ""


# --- the corpus: one bad doc aborts the run -------------------------------------------------


def test_one_bad_doc_aborts_the_whole_run_listing_every_error() -> None:
    good = doc()
    bad1 = doc(front=FRONT.replace("deals-stage-automation", "a").replace("[deals]", "[]"))
    bad2 = doc(front=FRONT.replace("deals-stage-automation", "b").replace("[deals]", "[dealz]"))
    with pytest.raises(IngestAborted) as exc:
        V.validate_corpus([("ok.md", good), ("a.md", bad1), ("b.md", bad2)])
    joined = "\n".join(exc.value.errors)
    assert "a.md" in joined and "b.md" in joined, "every bad doc is reported, not just the first"
    assert "ok.md" not in joined


def test_duplicate_doc_ids_across_files_abort() -> None:
    with pytest.raises(IngestAborted, match="deals-stage-automation") as exc:
        V.validate_corpus([("one.md", doc()), ("two.md", doc())])
    assert any("one.md" in e and "two.md" in e for e in exc.value.errors)


def test_an_empty_corpus_aborts() -> None:
    """An empty run must never become an empty live index."""
    with pytest.raises(IngestAborted, match="no docs"):
        V.validate_corpus([])


def test_the_repo_corpus_is_valid_and_tags_come_from_frontmatter() -> None:
    from chatbot.adapters.local_catalogue import load_catalogue

    known = frozenset(load_catalogue(ROOT / "data" / "module_catalogue.yaml").modules)
    docs = DocValidator(known, SCHEMA).read_corpus(ROOT / "data" / "docs")
    assert len(docs) == 42
    forecasting = next(d for d in docs if d.doc_id == "deals-forecasting")
    assert forecasting.modules == ("deals", "reports")
    assert forecasting.source == "deals/deals-forecasting.md"
