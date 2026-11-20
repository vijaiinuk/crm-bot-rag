"""Resolve `doc_id#anchor` eval labels to the chunks of one index version (S2.3.1).

A chunk satisfies its own section's label and every ancestor section's label, so a
`##` with no text of its own (no chunk) is found through its `###` children, and a
split section is found through any of its parts.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChunkRow:
    chunk_id: str
    doc_id: str
    anchor: str
    parent_anchor: str | None


class OrphanLabels(Exception):
    """Labels that match no chunk in the index. Fail, never count them as misses."""

    def __init__(self, labels: list[str]) -> None:
        super().__init__(
            f"{len(labels)} eval label(s) match no chunk in this index version: "
            + ", ".join(labels)
        )
        self.labels = labels


def label_index(rows: Iterable[ChunkRow]) -> dict[str, frozenset[str]]:
    """chunk_id -> every label it satisfies."""
    rows = list(rows)
    parent: dict[tuple[str, str], str] = {
        (r.doc_id, r.anchor): r.parent_anchor for r in rows if r.parent_anchor is not None
    }
    out: dict[str, frozenset[str]] = {}
    for r in rows:
        labels, seen, up = [f"{r.doc_id}#{r.anchor}"], {r.anchor}, r.parent_anchor
        while up and up not in seen:  # walk up the ancestors; `seen` guards a cycle
            seen.add(up)
            labels.append(f"{r.doc_id}#{up}")
            up = parent.get((r.doc_id, up))
        out[r.chunk_id] = frozenset(labels)
    return out


def check_labels(labels: Iterable[str], index: Mapping[str, frozenset[str]]) -> None:
    """Raise OrphanLabels listing (sorted, once each) every label no chunk satisfies."""
    satisfied = frozenset().union(*index.values()) if index else frozenset()
    orphans = sorted({label for label in labels if label not in satisfied})
    if orphans:
        raise OrphanLabels(orphans)
