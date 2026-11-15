"""Pure release logic: module diffs, heading anchors, orphaned labels, gate outcome.

Kept free of I/O so the mock and the real (Postgres) implementations share it.
"""

from collections.abc import Iterable, Mapping, Sequence

from chatbot.admin.models import ChangeKind, GateCheck, ModuleChange, OrphanedLabel, ReleaseStatus
from chatbot.ingest.anchors import anchors_of, slugify

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
