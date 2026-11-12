"""Pure release logic: module diffs, heading anchors, orphaned labels, gate outcome.

Kept free of I/O so the mock and the real (Postgres) implementations share it.
"""

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence

from chatbot.admin.models import ChangeKind, GateCheck, ModuleChange, OrphanedLabel, ReleaseStatus

# Re-exported for callers that only need the pure API.
__all__ = ["GateCheck", "anchors_of", "gate_outcome", "module_diff", "orphaned_labels", "slugify"]


def module_diff(
    live: Mapping[str, Sequence[str]], draft: Mapping[str, Sequence[str]]
) -> list[ModuleChange]:
    """Compare each doc's modules between the live release and the draft.

    A chunk is visible only to users who hold *all* of its modules (rule 5), so
    dropping any module lets more users see it: that is "widened", even when
    another module is added at the same time. Adding modules only narrows.
    """
    changes = []
    for doc_id in sorted(set(live) | set(draft)):
        before = sorted(live[doc_id]) if doc_id in live else None
        after = sorted(draft[doc_id]) if doc_id in draft else None
        if before is None:
            changes.append(ModuleChange(doc_id=doc_id, change="new", before=None, after=after))
            continue
        if after is None:
            changes.append(ModuleChange(doc_id=doc_id, change="retired", before=before, after=None))
            continue
        dropped = sorted(set(before) - set(after))
        added = sorted(set(after) - set(before))
        kind: ChangeKind = "widened" if dropped else "narrowed" if added else "unchanged"
        changes.append(
            ModuleChange(
                doc_id=doc_id, change=kind, before=before, after=after, dropped=dropped, added=added
            )
        )
    return changes


def slugify(heading: str) -> str:
    """Stable anchor slug: lowercase ASCII words joined by hyphens."""
    ascii_text = unicodedata.normalize("NFKD", heading).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^(```|~~~)")


def anchors_of(markdown: str) -> list[str]:
    """Anchors for every ATX heading outside fenced code blocks, in order."""
    anchors, in_fence = [], False
    for line in markdown.splitlines():
        if _FENCE.match(line.strip()):
            in_fence = not in_fence
            continue
        if not in_fence and (m := _HEADING.match(line)):
            anchors.append(slugify(m.group(2)))
    return anchors


def orphaned_labels(
    questions: Iterable[tuple[str, Sequence[str]]], anchors: Mapping[str, set[str]]
) -> list[OrphanedLabel]:
    """Eval labels (`doc_id#anchor`) that point at a doc or section not in the release."""
    found = []
    for question_id, labels in questions:
        for label in labels:
            doc_id, _, anchor = label.partition("#")
            if anchor not in anchors.get(doc_id, set()):
                found.append(OrphanedLabel(question_id=question_id, label=label))
    return found


def gate_outcome(checks: Sequence[GateCheck]) -> ReleaseStatus:
    """Any failure fails the release; otherwise anything needing a human waits for one."""
    statuses = {c.status for c in checks}
    if "fail" in statuses:
        return ReleaseStatus.failed
    if "needs_confirmation" in statuses:
        return ReleaseStatus.awaiting_confirmation
    return ReleaseStatus.live
