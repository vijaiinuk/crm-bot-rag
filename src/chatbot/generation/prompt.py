"""The versioned answer prompt (S3.1.3b): static rules first (prompt caching), then the
numbered excerpts, then the question.

Excerpts are numbered [1]..[n] rather than labelled by chunk ID: a model can't mistype
"[3]", and the server maps numbers back to chunks to verify citations.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from chatbot.ports.llm import Message
from chatbot.ports.retriever import Candidate

NOT_FOUND = "[[NOT_FOUND]]"  # the model's "the excerpts don't answer this" reply


class RestrictedContent(Exception):
    """A chunk outside the allowed modules reached prompt assembly. Never send it (rule 3)."""


@dataclass(frozen=True, slots=True)
class AnswerPrompt:
    prompt_id: str  # e.g. "answer_v1", from the file name
    system: str

    @property
    def version(self) -> str:
        """The id plus a hash of the text, so an unversioned edit still shows in traces."""
        return f"{self.prompt_id}@{hashlib.sha256(self.system.encode()).hexdigest()[:8]}"

    def build(
        self, question: str, excerpts: Sequence[Candidate], allowed_modules: frozenset[str]
    ) -> list[Message]:
        # Defence in depth: retrieval already filtered in SQL (rule 2); refuse anyway.
        for c in excerpts:
            if not set(c.modules) <= allowed_modules:
                raise RestrictedContent(f"{c.chunk_id} needs {list(c.modules)}")
        if not excerpts:
            raise ValueError("no excerpts: a below-threshold question never reaches the LLM")
        numbered = "\n\n".join(
            f"[{n}] {c.breadcrumb}\n{c.content}" for n, c in enumerate(excerpts, start=1)
        )
        return [
            Message("system", self.system),
            Message("user", f"Excerpts:\n\n{numbered}\n\nQuestion: {question}"),
        ]


def load_prompt(path: Path) -> AnswerPrompt:
    return AnswerPrompt(prompt_id=path.stem, system=path.read_text().strip())
