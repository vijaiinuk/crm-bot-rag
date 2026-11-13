"""S1.1.1: the CRM spec is the source of personas.yaml and module_catalogue.yaml."""

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from tools.spec import SpecError, derive_personas, load_raw, load_schema, parse

from tools import spec as specmod

SCHEMA = load_schema()
REPO_RAW: dict[str, Any] = load_raw(specmod.SPEC_PATH.read_text())

# A tiny spec: two modules besides core, one workflow that one persona fully
# holds and another misses by exactly one module.
TINY: dict[str, Any] = {
    "spec_version": 1,
    "restricted_contact": "Ask your admin.",
    "modules": {
        name: {
            "display_name": name.title(),
            "description": "d",
            "entities": ["e"],
            "ui_labels": ["l"],
        }
        for name in ["core", "deals", "campaigns"]
    },
    "roles": {"rep": {"modules": ["deals"]}, "manager": {"modules": ["deals", "campaigns"]}},
    "clients": {
        "acme": {"name": "Acme", "licensed": ["deals", "campaigns"]},
        "globex": {"name": "Globex", "licensed": ["deals"]},
    },
    "workflows": [
        {"id": "deal-email", "title": "t", "modules": ["deals", "campaigns"], "prerequisites": []}
    ],
}


def tiny() -> dict[str, Any]:
    return copy.deepcopy(TINY)


def errors_of(raw: Any) -> str:
    with pytest.raises(SpecError) as exc:
        parse(raw, SCHEMA)
    return "\n".join(exc.value.errors)


# --- the repo spec ----------------------------------------------------------------


def test_repo_spec_is_valid() -> None:
    parse(REPO_RAW, SCHEMA)


def test_existing_personas_keep_their_modules() -> None:
    """The demo, mock admin seed and API tests depend on these exact sets."""
    personas = derive_personas(parse(REPO_RAW, SCHEMA))
    assert personas["sales_manager@acme"] == {"core", "contacts", "deals", "campaigns", "reports"}
    assert personas["sales_rep@acme"] == {"core", "contacts", "deals"}
    assert personas["sales_rep@globex"] == {"core", "contacts", "deals"}
    assert personas["marketing_manager@globex"] == {"core", "contacts", "campaigns"}


@pytest.mark.parametrize(
    "generated",
    [specmod.PERSONAS_PATH, specmod.CATALOGUE_PATH],
    ids=lambda p: p.name,
)
def test_generated_files_match_the_spec(generated: Path) -> None:
    spec = parse(REPO_RAW, SCHEMA)
    expected = specmod.outputs(spec, specmod.PERSONAS_PATH, specmod.CATALOGUE_PATH)[generated]
    assert generated.read_text() == expected, f"{generated.name} is stale; run `make spec`"


# --- derivation ---------------------------------------------------------------------


def test_derivation_is_licensed_intersect_role_plus_core() -> None:
    assert derive_personas(parse(tiny(), SCHEMA)) == {
        "rep@acme": {"core", "deals"},
        "rep@globex": {"core", "deals"},
        "manager@acme": {"core", "deals", "campaigns"},
        "manager@globex": {"core", "deals"},  # role grants campaigns, client doesn't license it
    }


# --- fail closed --------------------------------------------------------------------


@pytest.mark.parametrize("section", ["roles", "clients", "workflows"])
def test_unknown_module_reference_is_rejected(section: str) -> None:
    raw = tiny()
    if section == "roles":
        raw["roles"]["rep"]["modules"].append("dealz")
    elif section == "clients":
        raw["clients"]["acme"]["licensed"].append("dealz")
    else:
        raw["workflows"][0]["modules"].append("dealz")
    assert "unknown modules ['dealz']" in errors_of(raw)


def test_missing_core_is_rejected() -> None:
    raw = tiny()
    del raw["modules"]["core"]
    assert "`core` must be defined" in errors_of(raw)


@pytest.mark.parametrize("section", ["roles", "clients"])
def test_granting_or_licensing_core_is_rejected(section: str) -> None:
    raw = tiny()
    if section == "roles":
        raw["roles"]["rep"]["modules"].append("core")
    else:
        raw["clients"]["acme"]["licensed"].append("core")
    assert "`core` is implicit" in errors_of(raw)


def test_duplicate_workflow_id_is_rejected() -> None:
    raw = tiny()
    raw["workflows"].append(copy.deepcopy(raw["workflows"][0]))
    assert "duplicate id 'deal-email'" in errors_of(raw)


def test_duplicate_yaml_key_is_rejected() -> None:
    """PyYAML would otherwise keep the second definition silently."""
    text = "modules:\n  deals: {a: 1}\n  deals: {a: 2}\n"
    with pytest.raises(SpecError, match="duplicate key 'deals'"):
        load_raw(text)


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda r: r.pop("roles"), "'roles' is a required property"),
        (lambda r: r["modules"]["deals"].pop("description"), "'description' is a required"),
        (lambda r: r["modules"].update({"Bad Name": r["modules"]["deals"]}), "does not match"),
        (lambda r: r["workflows"][0].update(modules=["deals"]), "is too short"),
        (lambda r: r["roles"]["rep"].update(modules=[]), "should be non-empty"),
        (lambda r: r.update(extra=1), "Additional properties"),
    ],
    ids=[
        "no-roles",
        "no-description",
        "bad-module-id",
        "one-module-workflow",
        "empty-grants",
        "extra-key",
    ],
)
def test_schema_rejects_bad_structure(mutate: Any, reason: str) -> None:
    raw = tiny()
    mutate(raw)
    assert reason in errors_of(raw)


# --- coverage -----------------------------------------------------------------------


def test_workflow_without_full_access_persona_is_rejected() -> None:
    raw = tiny()
    raw["clients"]["acme"]["licensed"] = ["deals"]
    assert "no persona holds all" in errors_of(raw)


def test_workflow_without_missing_one_persona_is_rejected() -> None:
    raw = tiny()
    raw["roles"]["rep"]["modules"] = ["deals", "campaigns"]
    raw["clients"]["globex"]["licensed"] = ["deals", "campaigns"]
    assert "no persona is missing exactly one" in errors_of(raw)


def test_module_no_persona_can_reach_is_rejected() -> None:
    raw = tiny()
    raw["modules"]["reports"] = copy.deepcopy(raw["modules"]["deals"])
    assert "modules/reports: no persona can access it" in errors_of(raw)


# --- CLI ------------------------------------------------------------------------------


def test_check_fails_on_stale_files_and_derive_fixes_them(tmp_path: Path) -> None:
    spec_file = tmp_path / "spec.yaml"
    spec_file.write_text(yaml.safe_dump(tiny()))
    paths = [
        "--spec",
        str(spec_file),
        "--personas",
        str(tmp_path / "p.yaml"),
        "--catalogue",
        str(tmp_path / "c.yaml"),
    ]
    assert specmod.main(["check", *paths]) == 1
    assert specmod.main(["derive", *paths]) == 0
    assert specmod.main(["check", *paths]) == 0


def test_invalid_spec_writes_nothing(tmp_path: Path) -> None:
    raw = tiny()
    raw["roles"]["rep"]["modules"].append("dealz")
    spec_file = tmp_path / "spec.yaml"
    spec_file.write_text(yaml.safe_dump(raw))
    out = tmp_path / "p.yaml"
    assert (
        specmod.main(
            [
                "derive",
                "--spec",
                str(spec_file),
                "--personas",
                str(out),
                "--catalogue",
                str(tmp_path / "c.yaml"),
            ]
        )
        == 1
    )
    assert not out.exists()
