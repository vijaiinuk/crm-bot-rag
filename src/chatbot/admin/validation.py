"""Upload validation for the admin app, on top of the shared fail-closed validator.

The contract the admin service relies on:
  - no identifiable doc_id -> UploadRejected (nothing to attach the attempt to)
  - otherwise a ParsedUpload whose `errors` decide validated vs rejected
The rules themselves live in chatbot.ingest.validate, shared with ingestion runs.
"""

import hashlib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from chatbot.ingest.validate import MAX_BYTES, DocValidator, load_frontmatter_schema

__all__ = ["MAX_BYTES", "ParsedUpload", "UploadRejected", "parse_upload"]

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "data" / "spec" / "doc_frontmatter.schema.json"


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


@cache
def _schema() -> dict[str, Any]:
    return load_frontmatter_schema(SCHEMA_PATH)


def parse_upload(filename: str, raw: bytes, known_modules: frozenset[str]) -> ParsedUpload:
    if not filename.lower().endswith((".md", ".markdown")):
        raise UploadRejected(["only markdown files (.md) can be uploaded in this release"])
    report = DocValidator(known_modules, _schema()).validate_doc(raw, source=filename)
    if report.doc_id is None:
        raise UploadRejected(
            report.errors
            or ["doc_id is missing or not a lowercase slug (e.g. deals-stage-automation)"]
        )
    return ParsedUpload(
        doc_id=report.doc_id,
        title=report.title,
        modules=sorted(set(report.modules)),
        anchors=report.anchors,
        markdown=raw.decode("utf-8"),
        content_sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
        errors=report.errors,
    )
