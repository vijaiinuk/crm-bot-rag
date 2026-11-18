"""S2.1.2: heading-aware chunker. Done when snapshots pass and no procedure is split.

Snapshots in tests/fixtures/chunker/*.snap.yaml are the reviewed expectations.
After a deliberate change, re-run with UPDATE_SNAPSHOTS=1 and review the diff.

Token counts here are words (`str.split`), so tests are deterministic and need no
tokenizer download. Fixture tests use a 40-word limit so small docs exercise
splitting.
"""

import hashlib
import os
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from chatbot.ingest.anchors import headings_of
from chatbot.ingest.chunker import INTRO_ANCHOR, Chunk, Chunker
from chatbot.ingest.validate import DocValidator, ValidDoc, load_frontmatter_schema

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "chunker"
SCHEMA = load_frontmatter_schema(ROOT / "data" / "spec" / "doc_frontmatter.schema.json")
KNOWN = frozenset({"core", "contacts", "deals", "campaigns", "reports"})
FIXTURE_NAMES = sorted(p.stem for p in FIXTURES.glob("*.md"))
FIXTURE_LIMIT = 40


def words(text: str) -> int:
    return len(text.split())


def load_fixture(name: str) -> ValidDoc:
    report = DocValidator(KNOWN, SCHEMA).validate_doc(
        (FIXTURES / f"{name}.md").read_bytes(), source=f"{name}.md"
    )
    assert report.doc is not None, report.errors
    return report.doc


def chunk(doc: ValidDoc, max_tokens: int = FIXTURE_LIMIT) -> list[Chunk]:
    return Chunker(words, max_tokens=max_tokens).chunk(doc)


# --- snapshots ------------------------------------------------------------------------------


class _Dumper(yaml.SafeDumper):
    pass


def _str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _str)


def dump_snapshot(rows: list[dict[str, Any]]) -> str:
    return yaml.dump(rows, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=1000)


def check_snapshot(path: Path, rows: list[dict[str, Any]]) -> None:
    text = dump_snapshot(rows)
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        path.write_text(text)
        return
    assert path.exists(), f"no snapshot {path.name}: run with UPDATE_SNAPSHOTS=1 and review it"
    assert yaml.safe_load(path.read_text()) == rows, f"{path.name} differs; review the change"


def row(c: Chunk) -> dict[str, Any]:
    return {
        "id": c.chunk_id,
        "parent": c.parent_anchor,
        "tokens": c.token_count,
        "oversized": c.oversized,
        "embed_text": c.embed_text,
    }


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_snapshot(name: str) -> None:
    check_snapshot(FIXTURES / f"{name}.snap.yaml", [row(c) for c in chunk(load_fixture(name))])


# --- the rules, one explicit test each ------------------------------------------------------


def test_one_chunk_per_section_with_a_title_breadcrumb() -> None:
    chunks = chunk(load_fixture("simple"))
    assert [c.chunk_id for c in chunks] == ["fx-simple#triggers:0", "fx-simple#add-an-action:0"]
    assert [c.breadcrumb for c in chunks] == ["Simple doc > Triggers", "Simple doc > Add an action"]
    assert chunks[0].text == "A trigger decides when an automation starts."
    assert chunks[0].embed_text == f"{chunks[0].breadcrumb}\n\n{chunks[0].text}"


def test_subsections_carry_their_parent_and_an_empty_parent_has_no_chunk() -> None:
    by_anchor = {c.anchor: c for c in chunk(load_fixture("nested"))}
    assert by_anchor["overview"].parent_anchor is None
    assert by_anchor["triggers"].parent_anchor == "overview"
    assert by_anchor["triggers"].breadcrumb == "Nested doc > Overview > Triggers"
    assert "limits" not in by_anchor, "a ## with no text of its own has no chunk"
    assert by_anchor["per-stage"].parent_anchor == "limits"


def test_intro_text_gets_the_reserved_anchor() -> None:
    first = chunk(load_fixture("intro"))[0]
    assert (first.chunk_id, first.breadcrumb) == (f"fx-intro#{INTRO_ANCHOR}:0", "Intro doc")
    assert first.parent_anchor is None


def test_a_long_section_splits_between_blocks_keeping_a_lead_in_with_its_list() -> None:
    parts = chunk(load_fixture("long-section"))
    assert [c.chunk_id for c in parts] == [
        "fx-long-section#importing:0",
        "fx-long-section#importing:1",
    ]
    assert all(c.token_count <= FIXTURE_LIMIT and not c.oversized for c in parts)
    assert parts[1].text.startswith("To start an import:\n\n1. Go to **Contacts**.")
    assert parts[1].breadcrumb == parts[0].breadcrumb


def test_a_procedure_over_the_limit_stays_whole_and_is_flagged() -> None:
    parts = chunk(load_fixture("oversized-procedure"))
    procedure = next(c for c in parts if c.text.startswith("1. "))
    assert procedure.oversized and procedure.token_count > FIXTURE_LIMIT
    assert procedure.text.rstrip().endswith("5. Check the notification when it finishes.")
    assert [c.oversized for c in parts] == [False, True, False]


def test_hash_lines_in_code_are_content_and_tables_stay_whole() -> None:
    chunks = chunk(load_fixture("table-and-code"))
    assert [c.anchor for c in chunks] == ["search-operators", "saved-searches"]
    assert "## not a heading" in chunks[1].text
    assert "| `owner:me` | Records you own |" in chunks[0].text


def test_modules_and_version_come_from_frontmatter() -> None:
    doc = load_fixture("nested")
    for c in chunk(doc):
        assert c.modules == ("deals", "campaigns") and c.doc_version == 2
        assert "deals" not in c.breadcrumb.lower(), "modules stay out of the embedded text"


def test_content_hash_is_the_sha256_of_the_embedded_text() -> None:
    for c in chunk(load_fixture("simple")):
        assert c.content_hash == hashlib.sha256(c.embed_text.encode()).hexdigest()


def test_chunking_is_deterministic() -> None:
    doc = load_fixture("long-section")
    assert chunk(doc) == chunk(doc)


def test_config_hash_tracks_the_recipe() -> None:
    base = Chunker(words, max_tokens=512, tokenizer_name="BAAI/bge-m3").config_hash
    assert base == Chunker(words, max_tokens=512, tokenizer_name="BAAI/bge-m3").config_hash
    assert base != Chunker(words, max_tokens=256, tokenizer_name="BAAI/bge-m3").config_hash
    assert base != Chunker(words, max_tokens=512, tokenizer_name="other").config_hash


@pytest.mark.parametrize("bad", [0, -1])
def test_the_limit_must_be_positive(bad: int) -> None:
    with pytest.raises(ValueError, match="max_tokens"):
        Chunker(words, max_tokens=bad)


# --- invariants: every doc, every limit -----------------------------------------------------
#
# The helpers below are a second, deliberately naive reading of the markdown, so
# the chunker is checked against something it does not share code with.

_FENCE = re.compile(r"^(```|~~~)")
_ITEM = re.compile(r"^(\d+\.|[-*+])\s")


def content_lines(body: str) -> list[str]:
    """Non-blank lines that are not section headings (code lines count as content)."""
    out, fence = [], False
    heading_texts = {h.text for h in headings_of(body)}
    for line in body.splitlines():
        if _FENCE.match(line):
            fence = not fence
        is_heading = (
            not fence and line.startswith("#") and line.lstrip("#").strip() in heading_texts
        )
        if line.strip() and not is_heading:
            out.append(line)
    return out


def protected_blocks(body: str) -> list[str]:
    """Every list, table and code block, as it appears in the body."""
    lines, blocks, i = body.splitlines(), [], 0
    while i < len(lines):
        line = lines[i]
        if _FENCE.match(line):
            j = i + 1
            while not _FENCE.match(lines[j]):
                j += 1
            blocks.append("\n".join(lines[i : j + 1]))
            i = j + 1
        elif line.startswith("|"):
            j = i
            while j < len(lines) and lines[j].startswith("|"):
                j += 1
            blocks.append("\n".join(lines[i:j]))
            i = j
        elif _ITEM.match(line):
            j = i + 1
            while j < len(lines):
                nxt = lines[j + 1] if j + 1 < len(lines) else ""
                in_list = bool(_ITEM.match(lines[j])) or lines[j].startswith(" ")
                # a blank line inside a loose list, followed by another item or continuation
                blank_inside = not lines[j].strip() and (bool(_ITEM.match(nxt)) or nxt[:1] == " ")
                if not (in_list or blank_inside):
                    break
                j += 1
            blocks.append("\n".join(lines[i:j]).rstrip())
            i = j
        else:
            i += 1
    return blocks


def check_invariants(doc: ValidDoc, chunks: list[Chunk], limit: int) -> None:
    assert chunks, doc.doc_id
    got = [line for c in chunks for line in c.text.splitlines() if line.strip()]
    assert got == content_lines(doc.body), f"{doc.doc_id}: text lost, duplicated or reordered"

    for block in protected_blocks(doc.body):
        holders = [c.chunk_id for c in chunks if block in c.text]
        assert len(holders) == 1, f"{doc.doc_id}: block split or repeated ({holders}):\n{block}"

    anchors = {h.anchor for h in doc.headings} | {INTRO_ANCHOR}
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids)), f"{doc.doc_id}: duplicate chunk ids"
    for c in chunks:
        assert c.anchor in anchors and c.chunk_id == f"{doc.doc_id}#{c.anchor}:{c.part}"
        assert c.modules == doc.modules
        assert c.token_count == words(c.embed_text)
        assert c.oversized == (c.token_count > limit)


@pytest.mark.parametrize("limit", [8, FIXTURE_LIMIT, 512])
@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_invariants_hold_on_fixtures_at_any_limit(name: str, limit: int) -> None:
    doc = load_fixture(name)
    check_invariants(doc, chunk(doc, limit), limit)


# --- the real corpus ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def corpus() -> list[ValidDoc]:
    from chatbot.adapters.local_catalogue import load_catalogue

    known = frozenset(load_catalogue(ROOT / "data" / "module_catalogue.yaml").modules)
    return DocValidator(known, SCHEMA).read_corpus(ROOT / "data" / "docs")


@pytest.mark.parametrize("limit", [100, 512])
def test_invariants_hold_on_the_corpus(corpus: list[ValidDoc], limit: int) -> None:
    """100 words forces real splits on real docs; 512 is the production limit."""
    for doc in corpus:
        check_invariants(doc, chunk(doc, limit), limit)


def test_the_corpus_is_one_chunk_per_section(corpus: list[ValidDoc]) -> None:
    chunks = [c for doc in corpus for c in chunk(doc, 512)]
    assert len(chunks) == sum(len(doc.headings) for doc in corpus) == 124
    assert all(c.part == 0 and not c.oversized for c in chunks)


def test_corpus_snapshot(corpus: list[ValidDoc]) -> None:
    """Any change that moves a chunk boundary on the real docs shows up as a diff."""
    rows = [{"id": c.chunk_id, "tokens": c.token_count} for doc in corpus for c in chunk(doc, 512)]
    check_snapshot(FIXTURES / "corpus.snap.yaml", rows)
