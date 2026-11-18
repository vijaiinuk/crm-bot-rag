"""Section anchors: the stable `doc_id#anchor` half that evals label against.

One definition shared by upload validation, the release gate, the synthetic
doc checks and (later) the chunker, so they can never disagree on an anchor.
"""

import re
import unicodedata
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^(```|~~~)")


@dataclass(frozen=True, slots=True)
class Heading:
    level: int
    text: str
    anchor: str


def slugify(heading: str) -> str:
    """Stable anchor slug: lowercase ASCII words joined by hyphens."""
    ascii_text = unicodedata.normalize("NFKD", heading).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def headings_of(markdown: str) -> list[Heading]:
    """Every ATX heading outside fenced code blocks, in order."""
    headings, in_fence = [], False
    for line in markdown.splitlines():
        if _FENCE.match(line.strip()):
            in_fence = not in_fence
            continue
        if not in_fence and (m := _HEADING.match(line)):
            headings.append(Heading(len(m.group(1)), m.group(2), slugify(m.group(2))))
    return headings


@dataclass(frozen=True, slots=True)
class Section:
    heading: Heading | None  # None for text before the first heading
    lines: tuple[str, ...]  # the section's own lines, heading line excluded


def sections_of(markdown: str) -> list[Section]:
    """The markdown cut at every heading, with the same rules as `headings_of`.

    Text before the first heading is a section with no heading (only if non-blank).
    """
    sections: list[Section] = []
    heading: Heading | None = None
    lines: list[str] = []
    in_fence = False
    for line in markdown.splitlines():
        if _FENCE.match(line.strip()):
            in_fence = not in_fence
        elif not in_fence and (m := _HEADING.match(line)):
            if heading is not None or any(x.strip() for x in lines):
                sections.append(Section(heading, tuple(lines)))
            heading = Heading(len(m.group(1)), m.group(2), slugify(m.group(2)))
            lines = []
            continue
        lines.append(line)
    if heading is not None or any(x.strip() for x in lines):
        sections.append(Section(heading, tuple(lines)))
    return sections


def anchors_of(markdown: str) -> list[str]:
    """Anchors for every ATX heading outside fenced code blocks, in order."""
    return [h.anchor for h in headings_of(markdown)]
