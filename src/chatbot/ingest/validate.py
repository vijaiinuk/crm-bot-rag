"""Fail-closed doc validation (S2.1.1, CLAUDE.md rule 4).

Used by admin uploads (one doc) and by ingestion runs (a whole corpus). The
rules: modules come only from frontmatter and must all be known; a doc the
chunker or the anchor parser could misread is an error, not a guess; and in a
run, any error in any doc aborts the whole run, listing every error found.
"""

import hashlib
import itertools
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from chatbot.ingest.anchors import Heading, headings_of

MAX_BYTES = 512 * 1024
_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z", re.DOTALL)
_FENCE = re.compile(r"^\s{0,3}(```|~~~)")
_SETEXT = re.compile(r"^\s{0,3}(=+|-+)\s*$")
_LIST_OR_TABLE = re.compile(r"^\s*([-*+]\s|\d+\.\s|\|)")
_DOC_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


class IngestAborted(Exception):
    """A run found invalid docs. Nothing from the run may be indexed."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__(f"{len(errors)} validation error(s):\n" + "\n".join(errors))
        self.errors = errors


@dataclass(frozen=True, slots=True)
class ValidDoc:
    source: str  # where it came from: a path relative to the corpus, or an upload name
    doc_id: str
    title: str
    modules: tuple[str, ...]  # exactly as in frontmatter; the only source of tags
    version: int
    body: str
    headings: tuple[Heading, ...]
    sha256: str  # of the raw file


@dataclass
class DocReport:
    source: str
    # Best-effort details, known even for invalid docs when frontmatter parses,
    # so an admin can see what a rejected upload was. Never index these.
    doc_id: str | None = None
    title: str | None = None
    modules: list[str] = field(default_factory=list)
    anchors: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    doc: ValidDoc | None = None


class _UniqueKeyLoader(yaml.SafeLoader):
    """PyYAML silently keeps the last of two duplicate keys; we reject them."""


def _construct_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        seen.add(key)
    return loader.construct_mapping(node)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def load_frontmatter_schema(path: Path) -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(path.read_text())
    return schema


def body_errors(body: str) -> list[str]:
    """Structure problems that would make chunks or anchors wrong."""
    errors: list[str] = []
    fence: str | None = None
    prev = ""
    for n, line in enumerate(body.splitlines(), start=1):
        if m := _FENCE.match(line):
            marker = m.group(1)
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            prev = ""
            continue
        underlines_text = (
            prev.strip() and not _LIST_OR_TABLE.match(prev) and not prev.lstrip().startswith("#")
        )
        if fence is None and _SETEXT.match(line) and underlines_text:
            errors.append(
                f"line {n}: underlined (setext) heading; use ## headings so anchors are found"
            )
        prev = line if fence is None else ""
    if fence is not None:
        errors.append("unclosed code block: everything after it would be read as code")
        return errors

    headings = headings_of(body)
    if not headings:
        errors.append("the body needs at least one ## section heading")
        return errors
    if any(h.level == 1 for h in headings):
        errors.append("level-1 heading: the title belongs in frontmatter; start sections at ##")
    elif headings[0].level != 2:
        errors.append(f"the first heading must be level 2 (##), not level {headings[0].level}")
    for before, after in itertools.pairwise(headings):
        if after.level > before.level + 1:
            errors.append(
                f"heading '{after.text}' skips from level {before.level} to level {after.level}"
            )
    seen: dict[str, str] = {}
    for h in headings:
        if not h.anchor:
            errors.append(f"heading '{h.text}' has no letters or digits, so no anchor")
        elif h.anchor in seen:
            errors.append(
                f"duplicate anchor '{h.anchor}' ('{seen[h.anchor]}' and '{h.text}'); "
                "headings must be unique within a doc"
            )
        else:
            seen[h.anchor] = h.text
    return errors


class DocValidator:
    def __init__(self, known_modules: frozenset[str], frontmatter_schema: dict[str, Any]) -> None:
        if not known_modules:
            raise ValueError("no known modules: refusing to validate against an empty list")
        self._known = known_modules
        self._schema = jsonschema.Draft202012Validator(frontmatter_schema)

    def validate_doc(self, raw: bytes, *, source: str) -> DocReport:
        report = DocReport(source)
        if len(raw) > MAX_BYTES:
            report.errors.append(f"file is larger than {MAX_BYTES // 1024} KB")
            return report
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            report.errors.append("file is not valid UTF-8 text")
            return report

        m = _FRONTMATTER.match(text)
        if not m:
            report.errors.append("missing frontmatter: the file must start with a --- block")
            return report
        try:
            meta: Any = yaml.load(m.group(1), Loader=_UniqueKeyLoader)  # noqa: S506 - safe subclass
        except yaml.constructor.ConstructorError as e:
            report.errors.append(f"frontmatter has a {e.problem}")
            return report
        except yaml.YAMLError:
            report.errors.append("frontmatter is not valid YAML")
            return report
        if not isinstance(meta, dict):
            report.errors.append("frontmatter must be a mapping of fields")
            return report
        doc_id = meta.get("doc_id")
        if isinstance(doc_id, str) and _DOC_ID.match(doc_id):
            report.doc_id = doc_id
        if isinstance(title := meta.get("title"), str) and title.strip():
            report.title = title
        if isinstance(mods := meta.get("modules"), list):
            report.modules = [x for x in mods if isinstance(x, str)]
        report.anchors = [h.anchor for h in headings_of(m.group(2))]

        problems = sorted(self._schema.iter_errors(meta), key=lambda p: list(p.absolute_path))
        for problem in problems:
            where = "/".join(str(p) for p in problem.absolute_path) or "frontmatter"
            report.errors.append(f"{where}: {problem.message}")
        modules = meta.get("modules")
        if isinstance(modules, list):
            for mod in modules:
                if isinstance(mod, str) and mod not in self._known:
                    report.errors.append(f"unknown module {mod!r} (known: {sorted(self._known)})")

        body = m.group(2)
        report.errors += body_errors(body)
        if report.errors:
            return report
        report.doc = ValidDoc(
            source=source,
            doc_id=meta["doc_id"],
            title=meta["title"],
            modules=tuple(meta["modules"]),
            version=meta["version"],
            body=body,
            headings=tuple(headings_of(body)),
            sha256=hashlib.sha256(raw).hexdigest(),
        )
        return report

    def validate_corpus(self, files: Sequence[tuple[str, bytes]]) -> list[ValidDoc]:
        """All docs valid, or IngestAborted listing every error in every doc."""
        if not files:
            raise IngestAborted(["no docs found: refusing to build an empty index"])
        errors: list[str] = []
        docs: list[ValidDoc] = []
        sources: dict[str, list[str]] = {}
        for source, raw in files:
            report = self.validate_doc(raw, source=source)
            errors += [f"{source}: {e}" for e in report.errors]
            if report.doc_id:
                sources.setdefault(report.doc_id, []).append(source)
            if report.doc:
                docs.append(report.doc)
        for doc_id, where in sources.items():
            if len(where) > 1:
                errors.append(
                    f"doc_id {doc_id!r} is used by more than one file: {', '.join(where)}"
                )
        if errors:
            raise IngestAborted(errors)
        return docs

    def read_corpus(self, docs_dir: Path) -> list[ValidDoc]:
        files = [
            (str(p.relative_to(docs_dir)), p.read_bytes()) for p in sorted(docs_dir.rglob("*.md"))
        ]
        return self.validate_corpus(files)
