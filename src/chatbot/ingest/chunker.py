"""Heading-aware chunker (S2.1.2). Design: docs/backlog.md, "S2.1.2 design".

One chunk per `##`/`###` section, holding only that section's own text. A
section over the token limit is split only between blocks (paragraph, whole
list, table, code block); a single block over the limit stays whole and is
flagged `oversized`. Modules are copied from the doc's frontmatter, never
inferred from text.

Three steps per section:
  1. blocks: cut the lines into paragraphs, lists, tables and code blocks;
  2. units:  glue a paragraph ending in ':' to the block it introduces;
  3. parts:  pack units in order while the embedded text fits the limit.
"""

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from chatbot.ingest.anchors import sections_of
from chatbot.ingest.validate import ValidDoc

CHUNKER_VERSION = 1
INTRO_ANCHOR = "_intro"  # text before the first heading; slugify never yields "_"
DEFAULT_MAX_TOKENS = 512
DEFAULT_TOKENIZER = "BAAI/bge-m3"

CountTokens = Callable[[str], int]

_FENCE = re.compile(r"^\s*(```|~~~)")
_TABLE = re.compile(r"^\s*\|")
_ITEM = re.compile(r"^\s{0,3}(\d+[.)]|[-*+])\s")


@dataclass(frozen=True, slots=True)
class Chunk:
    chunk_id: str  # f"{doc_id}#{anchor}:{part}"
    doc_id: str
    doc_version: int
    anchor: str
    parent_anchor: str | None  # the anchor of the enclosing heading (a `###` chunk's `##`)
    part: int  # 0 unless the section was split
    breadcrumb: str  # "Doc title > Section > Subsection"
    text: str  # the section's own markdown, no heading line; shown and cited
    embed_text: str  # breadcrumb + blank line + text; what gets embedded and searched
    modules: tuple[str, ...]  # exactly the doc's frontmatter modules
    token_count: int  # of embed_text
    oversized: bool  # one unsplittable block over the limit
    content_hash: str  # sha256 of embed_text; the embedding cache key


@dataclass(frozen=True, slots=True)
class _Span:
    """Lines [start, end) of a section: a block, or a unit of glued blocks."""

    start: int
    end: int
    kind: str  # paragraph | list | table | code


def _starts_block(line: str) -> bool:
    return bool(_FENCE.match(line) or _TABLE.match(line) or _ITEM.match(line))


def _blocks(lines: Sequence[str]) -> list[_Span]:
    """Cut a section into blocks. A block never ends inside a list, table or code block."""
    spans: list[_Span] = []
    n, i = len(lines), 0
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        j = i + 1
        if _FENCE.match(line):
            while j < n and not _FENCE.match(lines[j]):
                j += 1
            spans.append(_Span(i, min(j + 1, n), "code"))
            i = min(j + 1, n)
            continue
        if _TABLE.match(line):
            while j < n and _TABLE.match(lines[j]):
                j += 1
            kind = "table"
        elif _ITEM.match(line):
            while j < n:
                cur = lines[j]
                if cur.strip():
                    nested = _ITEM.match(cur) or cur[:1] in (" ", "\t")
                    # lazy continuation: unindented text straight after an item line
                    lazy = lines[j - 1].strip() and not _starts_block(cur)
                    if not (nested or lazy):
                        break
                    j += 1
                else:  # a blank line stays in the list if more of the list follows
                    k = j
                    while k < n and not lines[k].strip():
                        k += 1
                    if k == n or not (_ITEM.match(lines[k]) or lines[k][:1] in (" ", "\t")):
                        break
                    j = k
            kind = "list"
        else:
            while j < n and lines[j].strip() and not _starts_block(lines[j]):
                j += 1
            kind = "paragraph"
        spans.append(_Span(i, j, kind))
        i = j
    return spans


def _units(blocks: list[_Span], lines: Sequence[str]) -> list[_Span]:
    """Glue a lead-in paragraph ("To start an import:") to the block it introduces."""
    units: list[_Span] = []
    glue = False
    for b in blocks:
        if glue:
            units[-1] = _Span(units[-1].start, b.end, units[-1].kind)
        else:
            units.append(b)
        glue = b.kind == "paragraph" and lines[b.end - 1].rstrip().endswith(":")
    return units


class Chunker:
    def __init__(
        self,
        count_tokens: CountTokens,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        tokenizer_name: str = DEFAULT_TOKENIZER,
    ) -> None:
        if max_tokens <= 0:
            raise ValueError(f"max_tokens must be positive, got {max_tokens}")
        self._count = count_tokens
        self._max = max_tokens
        self._tokenizer = tokenizer_name

    @property
    def config_hash(self) -> str:
        """Identifies the chunking recipe: chunker version, limit and tokenizer."""
        recipe = {"chunker": CHUNKER_VERSION, "max_tokens": self._max, "tok": self._tokenizer}
        return hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()[:16]

    def chunk(self, doc: ValidDoc) -> list[Chunk]:
        chunks: list[Chunk] = []
        path: list[tuple[str, str]] = []  # (heading text, anchor) of the enclosing headings
        for section in sections_of(doc.body):
            if section.heading is None:
                anchor, parent, crumbs = INTRO_ANCHOR, None, []
            else:
                h = section.heading
                path = [*path[: h.level - 2], (h.text, h.anchor)]
                anchor = h.anchor
                parent = path[-2][1] if len(path) > 1 else None
                crumbs = [text for text, _ in path]
            breadcrumb = " > ".join([doc.title, *crumbs])
            for part, text in enumerate(self._parts(section.lines, breadcrumb)):
                embed_text = f"{breadcrumb}\n\n{text}"
                tokens = self._count(embed_text)
                chunks.append(
                    Chunk(
                        chunk_id=f"{doc.doc_id}#{anchor}:{part}",
                        doc_id=doc.doc_id,
                        doc_version=doc.version,
                        anchor=anchor,
                        parent_anchor=parent,
                        part=part,
                        breadcrumb=breadcrumb,
                        text=text,
                        embed_text=embed_text,
                        modules=doc.modules,
                        token_count=tokens,
                        oversized=tokens > self._max,
                        content_hash=hashlib.sha256(embed_text.encode()).hexdigest(),
                    )
                )
        return chunks

    def _parts(self, lines: Sequence[str], breadcrumb: str) -> list[str]:
        """Pack units in order; start a new part when the next unit would not fit."""

        def text(start: int, end: int) -> str:
            return "\n".join(lines[start:end])

        def fits(start: int, end: int) -> bool:
            return self._count(f"{breadcrumb}\n\n{text(start, end)}") <= self._max

        units = _units(_blocks(lines), lines)
        if not units:
            return []  # a heading with no text of its own (e.g. a ## before its ###s)
        parts: list[str] = []
        start, end = units[0].start, units[0].end
        for u in units[1:]:
            if fits(start, u.end):
                end = u.end
            else:
                parts.append(text(start, end))
                start, end = u.start, u.end
        parts.append(text(start, end))
        return parts
