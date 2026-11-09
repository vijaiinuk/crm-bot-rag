from pathlib import Path

import pytest

from chatbot.adapters.local_entitlements import LocalEntitlementProvider, PersonaFileError
from chatbot.ports.entitlements import EntitlementError, Principal

REPO_PERSONAS = Path(__file__).parents[2] / "data" / "personas.yaml"


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "personas.yaml"
    p.write_text(text)
    return p


async def test_repo_personas_file_loads() -> None:
    provider = LocalEntitlementProvider.from_file(REPO_PERSONAS)
    got = await provider.resolve(Principal(sub="u", tenant="globex", role="sales_rep"))
    assert got == frozenset({"core", "contacts", "deals"})


async def test_unknown_persona_raises() -> None:
    provider = LocalEntitlementProvider.from_file(REPO_PERSONAS)
    with pytest.raises(EntitlementError):
        await provider.resolve(Principal(sub="u", tenant="nowhere", role="sales_rep"))


async def test_result_is_immutable() -> None:
    provider = LocalEntitlementProvider.from_file(REPO_PERSONAS)
    got = await provider.resolve(Principal(sub="u", tenant="acme", role="sales_manager"))
    assert isinstance(got, frozenset)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("known_modules: [core, deals]\npersonas:\n  rep@acme: [core, dealz]\n", "unknown"),
        ("known_modules: [core, deals]\npersonas:\n  rep@acme: [deals]\n", "core"),
        ("known_modules: [core]\npersonas:\n  rep@acme: []\n", "non-empty"),
        ("known_modules: [core]\npersonas:\n  rep_acme: [core]\n", "role@client"),
        ("known_modules: []\npersonas:\n  rep@acme: [core]\n", "known_modules"),
        ("known_modules: [core]\npersonas: {}\n", "personas"),
        ("- just a list\n", "mapping"),
        ("personas: [unclosed\n", "cannot read"),
    ],
    ids=[
        "unknown-module",
        "missing-core",
        "empty-modules",
        "bad-id",
        "no-known",
        "no-personas",
        "not-a-mapping",
        "bad-yaml",
    ],
)
def test_bad_file_aborts_loading(tmp_path: Path, text: str, reason: str) -> None:
    with pytest.raises(PersonaFileError, match=reason):
        LocalEntitlementProvider.from_file(write(tmp_path, text))


def test_missing_file_aborts_loading(tmp_path: Path) -> None:
    with pytest.raises(PersonaFileError):
        LocalEntitlementProvider.from_file(tmp_path / "nope.yaml")
