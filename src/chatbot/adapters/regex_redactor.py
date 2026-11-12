"""Interim regex redaction: emails, phone numbers, long digit runs.

Good enough to keep obvious PII out of stored transcripts in the mock. The
guardrails story replaces it (names and addresses need more than regex).
"""

import re

_EMAIL = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
# +44 20 7946 0958 · (555) 123-4567 · 555-123-4567: 10+ digits with separators.
_PHONE = re.compile(
    r"(?<![\w.])(?:\+\d{1,3}[ .-]?)?(?:\(\d{2,4}\)[ .-]?|\d{2,4}[ .-])\d{3,4}[ .-]\d{4}(?![\w])"
)
# Card or account numbers: 9+ unbroken digits, or 3+ groups of four (4111 1111 1111 1111).
_LONG_NUMBER = re.compile(r"(?<![\w.])(?:\d{9,}|\d{4}(?:[ -]\d{4}){2,})(?![\w.]?\d)")


class RegexRedactor:
    def redact(self, text: str) -> str:
        text = _EMAIL.sub("[email]", text)
        text = _LONG_NUMBER.sub("[number]", text)  # before phones: card groups look phone-like
        return _PHONE.sub("[phone]", text)
