"""Mock upload validation.

Deliberately minimal: S2.1.1 builds the real fail-closed validator (schema,
chunking pre-checks) and replaces this module. The contract it keeps:
  - no identifiable doc_id -> UploadRejected (nothing to attach the attempt to)
  - otherwise a ParsedUpload whose `errors` decide validated vs rejected
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from chatbot.admin.releases import anchors_of

MAX_BYTES = 512 * 1024
_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z", re.DOTALL)
_DOC_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


class UploadRejected(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class ParsedUpload:
    doc_id: str
    title: str | None
    modules: list[str]
    anchors: list[str]
    markdown: str
    content_sha256: str
    size_bytes: int
    errors: list[str] = field(default_factory=list)


def parse_upload(filename: str, raw: bytes, known_modules: frozenset[str]) -> ParsedUpload:
    if not filename.lower().endswith((".md", ".markdown")):
        raise UploadRejected(["only markdown files (.md) can be uploaded in this release"])
    if len(raw) > MAX_BYTES:
        raise UploadRejected([f"file is larger than {MAX_BYTES // 1024} KB"])
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise UploadRejected(["file is not valid UTF-8 text"]) from None

    m = _FRONTMATTER.match(text)
    if not m:
        raise UploadRejected(["missing frontmatter: the file must start with a --- block"])
    try:
        meta: Any = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        raise UploadRejected(["frontmatter is not valid YAML"]) from None
    if not isinstance(meta, dict):
        raise UploadRejected(["frontmatter must be a mapping of fields"])
    doc_id = meta.get("doc_id")
    if not isinstance(doc_id, str) or not _DOC_ID.match(doc_id):
        raise UploadRejected(
            ["doc_id is missing or not a lowercase slug (e.g. deals-stage-automation)"]
        )

    errors: list[str] = []
    title = meta.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append("title is missing")
        title = None

    modules_raw = meta.get("modules")
    modules: list[str] = []
    if not isinstance(modules_raw, list) or not modules_raw:
        errors.append("modules must list at least one module (use `core` for shared content)")
    elif not all(isinstance(x, str) for x in modules_raw):
        errors.append("modules must be a list of module names")
    else:
        modules = sorted(set(modules_raw))
        unknown = sorted(set(modules) - known_modules)
        if unknown:
            errors.append(f"unknown module(s): {', '.join(unknown)}")

    body = m.group(2)
    return ParsedUpload(
        doc_id=doc_id,
        title=title,
        modules=modules,
        anchors=anchors_of(body),
        markdown=text,
        content_sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
        errors=errors,
    )
