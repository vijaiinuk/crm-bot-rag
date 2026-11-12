import pytest

from chatbot.adapters.regex_redactor import RegexRedactor

R = RegexRedactor()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("email jane.doe@example.com about it", "email [email] about it"),
        ("cc J.O'Neil+crm@sub.example.co.uk", "cc [email]"),
        ("call +44 20 7946 0958 today", "call [phone] today"),
        ("or (555) 123-4567", "or [phone]"),
        ("or 555-123-4567.", "or [phone]."),
        ("account 4111 1111 1111 1111", "account [number]"),
        ("ref 123456789012", "ref [number]"),
    ],
)
def test_masks_personal_data(text: str, expected: str) -> None:
    assert R.redact(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "how do I move a deal to stage 2",
        "what changed in the 2026 release",
        "import 500 contacts from a CSV",
        "set a 30-day reminder",
        "version 1.2.3",
    ],
)
def test_leaves_ordinary_text_alone(text: str) -> None:
    assert R.redact(text) == text
