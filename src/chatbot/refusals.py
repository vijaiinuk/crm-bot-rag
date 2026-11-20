"""Templated refusals (CLAUDE.md rules 3 and 7).

Built only from the public module catalogue, never from retrieved or
generated content, so a refusal cannot leak what it is refusing.
"""

from collections.abc import Iterable

from chatbot.ports.catalogue import ModuleCatalogue


def restricted_message(missing_modules: Iterable[str], catalogue: ModuleCatalogue) -> str:
    names = sorted(catalogue.display_name(m) for m in missing_modules)
    if not names:
        raise ValueError("restricted refusal needs at least one module")
    return (
        f"This question involves {_join(names)}, which isn't included in your current access. "
        f"{catalogue.restricted_contact}"
    )


def partial_access_note(missing_modules: Iterable[str], catalogue: ModuleCatalogue) -> str:
    """Appended to an answer built from allowed docs when the question also seems to
    involve modules the user lacks. Templated from the catalogue, never generated."""
    names = sorted(catalogue.display_name(m) for m in missing_modules)
    if not names:
        raise ValueError("a partial-access note needs at least one module")
    return (
        f"Parts of this may involve {_join(names)}, which isn't included in your current "
        f"access, so this answer covers only what you can use. {catalogue.restricted_contact}"
    )


def not_found_message() -> str:
    return (
        "I couldn't find this in the help documentation. "
        "Try rephrasing, or ask about a specific CRM feature."
    )


def _join(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"
