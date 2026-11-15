"""Deterministic stand-in for the RAG pipeline.

Keyword rules pick canned "documents", so every client state is reachable on
purpose. It applies the same permission semantics the real pipeline must:
an answer needs every module it draws on; otherwise it's a templated refusal
and none of the content is streamed.
"""

import asyncio
import re
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from chatbot.events import Citation, Citations, ContentEvent, Refusal, Token, TokenUsage, Usage
from chatbot.ports.catalogue import ModuleCatalogue
from chatbot.ports.entitlements import Principal
from chatbot.ports.responder import Query, Versions
from chatbot.refusals import not_found_message, restricted_message

ERROR_TRIGGER = "simulate:error"


@dataclass(frozen=True, slots=True)
class MockDoc:
    doc_id: str
    anchor: str
    title: str
    breadcrumb: str
    module: str
    pattern: re.Pattern[str]
    body: str

    def citation(self) -> Citation:
        return Citation(
            chunk_id=f"mock:{self.doc_id}#{self.anchor}:0",
            doc_id=self.doc_id,
            anchor=self.anchor,
            title=self.title,
            breadcrumb=self.breadcrumb,
        )


def _words(*stems: str) -> re.Pattern[str]:
    """Match words starting with any stem: `deal` matches `deals`, not `ideal`."""
    return re.compile(rf"\b(?:{'|'.join(stems)})", re.IGNORECASE)


MOCK_DOCS: tuple[MockDoc, ...] = (
    MockDoc(
        doc_id="deals-stage-automation",
        anchor="triggers",
        title="Automating deal stage changes",
        breadcrumb="Deals > Stage automation > Triggers",
        module="deals",
        pattern=_words("deal", "pipeline", "stage"),
        body=(
            "**Deals:** stage changes can trigger automations.\n\n"
            "1. Open **Deals → Pipeline settings**.\n"
            "2. Choose the stage and select **Add trigger**.\n"
            "3. Pick the action to run when a deal enters that stage, then **Save**."
        ),
    ),
    MockDoc(
        doc_id="campaigns-triggered-emails",
        anchor="setup",
        title="Setting up triggered emails",
        breadcrumb="Campaigns > Triggered emails > Setup",
        module="campaigns",
        pattern=_words("campaign", "email"),
        body=(
            "**Campaigns:** triggered emails send automatically when a condition is met.\n\n"
            "1. Go to **Campaigns → Triggered emails** and select **New**.\n"
            "2. Choose the trigger event and the audience.\n"
            "3. Pick a template, review it, and select **Activate**."
        ),
    ),
    MockDoc(
        doc_id="reports-dashboards",
        anchor="create-a-dashboard",
        title="Creating a dashboard",
        breadcrumb="Reports > Dashboards > Create a dashboard",
        module="reports",
        pattern=_words("report", "dashboard"),
        body=(
            "**Reports:** dashboards group saved reports on one page.\n\n"
            "1. Open **Reports → Dashboards** and select **New dashboard**.\n"
            "2. Add widgets from your saved reports.\n"
            "3. Set the date range and sharing, then **Save**."
        ),
    ),
    MockDoc(
        doc_id="contacts-import",
        anchor="csv",
        title="Importing contacts from CSV",
        breadcrumb="Contacts > Import > CSV",
        module="contacts",
        pattern=_words("contact", "import"),
        body=(
            "**Contacts:** you can bulk-import people from a CSV file.\n\n"
            "1. Go to **Contacts → Import** and upload the file.\n"
            "2. Map each column to a contact field.\n"
            "3. Review duplicates and select **Import**."
        ),
    ),
)

_TOKEN_RE = re.compile(r"\S+\s*|\s+")


class MockResponder:
    def __init__(self, catalogue: ModuleCatalogue, *, token_delay_s: float = 0.0) -> None:
        self._catalogue = catalogue
        self._delay = token_delay_s

    @property
    def versions(self) -> Versions:
        return Versions(index_version="mock", prompt_version="mock", model_id="mock")

    async def respond(
        self, query: Query, principal: Principal, allowed_modules: frozenset[str]
    ) -> AsyncGenerator[ContentEvent, None]:
        message = query.message
        if ERROR_TRIGGER in message.lower():
            yield Token(text="Let me check ")
            raise RuntimeError("simulated responder failure")

        hits = [d for d in MOCK_DOCS if d.pattern.search(message)]
        if not hits:
            yield Refusal(kind="not_found", message=not_found_message())
            return

        missing = {d.module for d in hits} - allowed_modules
        if missing:
            yield Refusal(
                kind="restricted",
                message=restricted_message(missing, self._catalogue),
                missing_modules=sorted(missing),
            )
            return

        answer = "\n\n".join(d.body for d in hits)
        for piece in _TOKEN_RE.findall(answer):
            if self._delay:
                await asyncio.sleep(self._delay)
            yield Token(text=piece)
        yield Citations(items=[d.citation() for d in hits])
        yield Usage(
            usage=TokenUsage(input_tokens=len(message.split()), output_tokens=len(answer.split()))
        )
