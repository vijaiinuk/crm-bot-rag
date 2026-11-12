from typing import Protocol


class Redactor(Protocol):
    """Removes personal data from text before it is stored or traced."""

    def redact(self, text: str) -> str: ...
