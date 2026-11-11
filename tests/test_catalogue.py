from pathlib import Path

import pytest

from chatbot.adapters.local_catalogue import CatalogueFileError, check_covers, load_catalogue
from chatbot.adapters.local_entitlements import LocalEntitlementProvider
from chatbot.api.app import create_app
from chatbot.config import Settings
from chatbot.refusals import restricted_message

DATA = Path(__file__).parents[1] / "data"


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "catalogue.yaml"
    p.write_text(text)
    return p


def test_repo_catalogue_covers_repo_personas() -> None:
    catalogue = load_catalogue(DATA / "module_catalogue.yaml")
    personas = LocalEntitlementProvider.from_file(DATA / "personas.yaml")
    check_covers(catalogue, personas.modules)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("modules:\n  deals: {display_name: Deals, description: d}\n", "restricted_contact"),
        ("restricted_contact: ask\nmodules: {}\n", "modules"),
        ("restricted_contact: ask\nmodules:\n  deals: {description: d}\n", "display_name"),
        ("restricted_contact: ask\nmodules:\n  deals: {display_name: Deals}\n", "description"),
        ("restricted_contact: ask\nmodules:\n  deals: Deals\n", "mapping"),
        ("[1, 2]\n", "mapping"),
        ("modules: [unclosed\n", "cannot read"),
    ],
)
def test_bad_catalogue_aborts(tmp_path: Path, text: str, reason: str) -> None:
    with pytest.raises(CatalogueFileError, match=reason):
        load_catalogue(write(tmp_path, text))


def test_app_refuses_to_start_if_catalogue_misses_a_persona_module(tmp_path: Path) -> None:
    catalogue = write(
        tmp_path,
        "restricted_contact: ask\nmodules:\n  core: {display_name: Core, description: d}\n",
    )
    settings = Settings(env="test", catalogue_path=catalogue)
    entitlements = LocalEntitlementProvider({"rep@acme": frozenset({"core", "deals"})})
    with pytest.raises(CatalogueFileError, match="deals"):
        create_app(settings, entitlements=entitlements)


def test_restricted_message_lists_display_names() -> None:
    catalogue = load_catalogue(DATA / "module_catalogue.yaml")
    one = restricted_message(["campaigns"], catalogue)
    two = restricted_message(["reports", "campaigns"], catalogue)
    assert "Campaigns" in one and catalogue.restricted_contact in one
    assert "Campaigns and Reports" in two, "sorted, human-joined"
    assert "campaigns" not in two, "show display names, not module ids"
