"""Deterministic seed data for the admin mock.

Times are relative to `now`, so staleness and "uploaded N days ago" stay
meaningful whenever the API starts. The scenario it sets up:

  r1, r2 superseded · r3 live · draft r4 with
    deals-forecasting v2      [deals, reports] -> [reports]   widens access
    deals-stage-automation v3 "Triggers" renamed            orphans q-0001's label
    core-search-tips v1       a brand-new doc
  contacts-merge-duplicates and reports-scheduled-exports are stale (>90 days).
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from chatbot.adapters.mock_admin.repository import InMemoryAdminRepository
from chatbot.admin.models import (
    Document,
    DocumentVersionContent,
    EvalLabelRef,
    Release,
    ReleaseStatus,
    VersionStatus,
)
from chatbot.admin.releases import anchors_of

UPLOADER = "seed@ops"


@dataclass(frozen=True)
class V:
    days_ago: int
    modules: tuple[str, ...]
    sections: tuple[str, ...]


DOCS: dict[str, tuple[str, list[V]]] = {
    "deals-stage-automation": (
        "Automating deal stage changes",
        [
            V(80, ("deals",), ("Triggers", "Actions")),
            V(25, ("deals",), ("Triggers", "Actions", "Testing an automation")),
            V(2, ("deals",), ("Stage triggers", "Actions", "Testing an automation")),
        ],
    ),
    "deals-pipeline-setup": (
        "Setting up a pipeline",
        [V(70, ("deals",), ("Create a pipeline", "Edit stages"))],
    ),
    "deals-forecasting": (
        "Forecasting deals",
        [
            V(40, ("deals", "reports"), ("Forecast categories", "Forecast reports")),
            V(1, ("reports",), ("Forecast categories", "Forecast reports")),
        ],
    ),
    "campaigns-triggered-emails": (
        "Setting up triggered emails",
        [
            V(85, ("campaigns",), ("Setup", "Templates")),
            V(20, ("campaigns",), ("Setup", "Templates", "Send limits")),
        ],
    ),
    "campaigns-audiences": (
        "Building audiences",
        [V(50, ("campaigns",), ("Build an audience", "Exclusions"))],
    ),
    "campaigns-deal-triggers": (
        "Emailing contacts when a deal changes stage",
        [V(30, ("campaigns", "deals"), ("Connect a stage to a campaign", "Choose recipients"))],
    ),
    "contacts-import": (
        "Importing contacts",
        [
            V(88, ("contacts",), ("CSV",)),
            V(45, ("contacts",), ("CSV", "Mapping fields")),
            V(12, ("contacts",), ("CSV", "Mapping fields", "Duplicates")),
        ],
    ),
    "contacts-merge-duplicates": (
        "Merging duplicate contacts",
        [V(120, ("contacts",), ("Merge two contacts",))],
    ),
    "reports-dashboards": (
        "Creating dashboards",
        [V(60, ("reports",), ("Create a dashboard", "Share a dashboard"))],
    ),
    "reports-scheduled-exports": (
        "Scheduling exports",
        [V(200, ("reports",), ("Schedule an export",))],
    ),
    "core-navigation": ("Finding your way around", [V(89, ("core",), ("Search", "Favourites"))]),
    "core-notifications": (
        "Notification settings",
        [V(65, ("core",), ("Email notifications", "In-app notifications"))],
    ),
    "core-search-tips": ("Search tips", [V(1, ("core",), ("Search operators", "Saved searches"))]),
}

# (created days ago, status). Each release takes, per doc, the newest version
# uploaded on or before its creation day; the draft is listed explicitly.
RELEASES = [
    ("r1", 60, ReleaseStatus.superseded),
    ("r2", 30, ReleaseStatus.superseded),
    ("r3", 10, ReleaseStatus.live),
]
DRAFT_CHANGES = {"deals-stage-automation": 3, "deals-forecasting": 2, "core-search-tips": 1}

EVAL_LABELS = [
    ("q-0001", ["deals-stage-automation#triggers"]),
    ("q-0002", ["campaigns-triggered-emails#setup"]),
    (
        "q-0003",
        ["deals-stage-automation#actions", "campaigns-deal-triggers#connect-a-stage-to-a-campaign"],
    ),
    ("q-0004", ["contacts-import#csv"]),
    ("q-0005", ["reports-dashboards#create-a-dashboard"]),
    ("q-0006", ["core-navigation#search"]),
]


def _markdown(doc_id: str, title: str, version: int, v: V) -> str:
    body = "\n\n".join(
        f"## {s}\n\nHow to {s.lower()} in {title.lower()}. (Synthetic text for the admin mock.)"
        for s in v.sections
    )
    return (
        f"---\ndoc_id: {doc_id}\ntitle: {title}\nmodules: [{', '.join(v.modules)}]\n"
        f"version: {version}\n---\n# {title}\n\n{body}\n"
    )


def seed(repo: InMemoryAdminRepository, now: datetime) -> None:
    for doc_id, (title, versions) in DOCS.items():
        doc = Document(doc_id=doc_id)
        for n, v in enumerate(versions, start=1):
            md = _markdown(doc_id, title, n, v)
            raw = md.encode()
            doc.versions.append(
                DocumentVersionContent(
                    doc_id=doc_id,
                    version=n,
                    title=title,
                    modules=sorted(v.modules),
                    anchors=anchors_of(md.split("---\n", 2)[2]),
                    status=VersionStatus.validated,
                    uploaded_by=UPLOADER,
                    uploaded_at=now - timedelta(days=v.days_ago, hours=n),
                    content_sha256=hashlib.sha256(raw).hexdigest(),
                    size_bytes=len(raw),
                    markdown=md,
                )
            )
        repo.documents[doc_id] = doc

    def contents_at(days_ago: int) -> dict[str, int]:
        out = {}
        for doc_id, (_, versions) in DOCS.items():
            eligible = [n for n, v in enumerate(versions, start=1) if v.days_ago >= days_ago]
            if eligible:
                out[doc_id] = max(eligible)
        return out

    for rid, days, status in RELEASES:
        created = now - timedelta(days=days)
        repo.releases[rid] = Release(
            id=rid,
            status=status,
            documents=contents_at(days),
            created_by=UPLOADER,
            created_at=created,
            published_by=UPLOADER,
            published_at=created,
            live_since=created,
        )
    live = repo.releases["r3"].documents
    repo.releases["r4"] = Release(
        id="r4",
        status=ReleaseStatus.draft,
        documents=live | DRAFT_CHANGES,
        created_by=UPLOADER,
        created_at=now - timedelta(days=1),
    )
    repo.eval_labels = [EvalLabelRef(question_id=q, labels=labels) for q, labels in EVAL_LABELS]
