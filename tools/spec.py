"""Validate the CRM spec and derive the files generated from it.

    python -m tools.spec validate   # schema + reference + coverage checks
    python -m tools.spec derive     # (re)write personas.yaml and module_catalogue.yaml
    python -m tools.spec check      # validate, and fail if the generated files are stale

Fail closed: any error stops the run and nothing is written. The generated
files stay the runtime contract (the API's loaders read them, not the spec).
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "data" / "spec" / "crm_spec.yaml"
SCHEMA_PATH = ROOT / "data" / "spec" / "crm_spec.schema.json"
PERSONAS_PATH = ROOT / "data" / "personas.yaml"
CATALOGUE_PATH = ROOT / "data" / "module_catalogue.yaml"

CORE = "core"
GENERATED = "# GENERATED from data/spec/crm_spec.yaml by `make spec`. Do not edit by hand.\n"


class SpecError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


@dataclass(frozen=True, slots=True)
class Module:
    name: str
    display_name: str
    description: str


@dataclass(frozen=True, slots=True)
class Workflow:
    id: str
    title: str
    modules: frozenset[str]


@dataclass(frozen=True, slots=True)
class Spec:
    restricted_contact: str
    modules: dict[str, Module]  # spec order; also the order used in generated files
    roles: dict[str, frozenset[str]]
    clients: dict[str, frozenset[str]]
    workflows: list[Workflow]


class _UniqueKeyLoader(yaml.SafeLoader):
    """PyYAML keeps the last of two duplicate keys silently; a duplicated
    module or role would hide an edit, so reject it instead."""


def _construct_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        seen.add(key)
    return loader.construct_mapping(node)


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def load_raw(text: str) -> Any:
    try:
        return yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError as e:
        raise SpecError([f"cannot parse spec: {e}"]) from e


def load_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(path.read_text())
    return schema


def parse(raw: Any, schema: dict[str, Any]) -> Spec:
    """Schema first (structure), then the checks a schema can't express."""
    validator = jsonschema.Draft202012Validator(schema)
    structural = sorted(validator.iter_errors(raw), key=lambda e: list(e.absolute_path))
    if structural:
        raise SpecError([f"{_where(e.absolute_path)}: {e.message}" for e in structural])

    modules = {
        name: Module(name, m["display_name"], m["description"])
        for name, m in raw["modules"].items()
    }
    roles = {name: frozenset(r["modules"]) for name, r in raw["roles"].items()}
    clients = {name: frozenset(c["licensed"]) for name, c in raw["clients"].items()}
    workflows = [Workflow(w["id"], w["title"], frozenset(w["modules"])) for w in raw["workflows"]]
    spec = Spec(raw["restricted_contact"], modules, roles, clients, workflows)

    errors = _reference_errors(spec)
    if not errors:  # coverage is meaningless while references are broken
        errors = _coverage_errors(spec)
    if errors:
        raise SpecError(errors)
    return spec


def _where(path: Any) -> str:
    return "/".join(str(p) for p in path) or "(root)"


def _reference_errors(spec: Spec) -> list[str]:
    errors: list[str] = []
    known = spec.modules.keys()
    if CORE not in known:
        errors.append(f"modules: `{CORE}` must be defined (every persona gets it)")

    refs: list[tuple[str, frozenset[str]]] = [
        *((f"roles/{n}", m) for n, m in spec.roles.items()),
        *((f"clients/{n}", m) for n, m in spec.clients.items()),
        *((f"workflows/{w.id}", w.modules) for w in spec.workflows),
    ]
    for where, mods in refs:
        unknown = sorted(mods - known)
        if unknown:
            errors.append(f"{where}: unknown modules {unknown}")
        if CORE in mods and not where.startswith("workflows/"):
            errors.append(f"{where}: `{CORE}` is implicit; don't grant or license it")

    ids = [w.id for w in spec.workflows]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"workflows: duplicate id {dup!r}")
    return errors


def derive_personas(spec: Spec) -> dict[str, frozenset[str]]:
    """Every role x client: (licensed ∩ role grants) + core."""
    return {
        f"{role}@{client}": frozenset({CORE} | (granted & licensed))
        for role, granted in spec.roles.items()
        for client, licensed in spec.clients.items()
    }


def _coverage_errors(spec: Spec) -> list[str]:
    personas = derive_personas(spec)
    errors: list[str] = []
    for w in spec.workflows:
        missing_counts = [len(w.modules - allowed) for allowed in personas.values()]
        if 0 not in missing_counts:
            errors.append(f"workflows/{w.id}: no persona holds all of {sorted(w.modules)}")
        if 1 not in missing_counts:
            errors.append(f"workflows/{w.id}: no persona is missing exactly one module")
    reachable = frozenset().union(*personas.values())
    for name in spec.modules.keys() - reachable:
        errors.append(f"modules/{name}: no persona can access it, so it can't be evaluated")
    return errors


def _ordered(spec: Spec, modules: frozenset[str]) -> list[str]:
    return [m for m in spec.modules if m in modules]


def render_personas(spec: Spec) -> str:
    lines = [
        GENERATED,
        "# Contract: persona ID (`role@client`) -> allowed modules\n",
        "# (licensed ∩ role-permitted, plus `core`).\n",
        "# `known_modules` is the closed set of module names; anything else aborts loading.\n",
        f"known_modules: [{', '.join(spec.modules)}]\n",
        "\n",
        "personas:\n",
    ]
    for persona, allowed in derive_personas(spec).items():
        lines.append(f"  {persona}: [{', '.join(_ordered(spec, allowed))}]\n")
    return "".join(lines)


def render_catalogue(spec: Spec) -> str:
    body = {
        "restricted_contact": spec.restricted_contact,
        "modules": {
            m.name: {"display_name": m.display_name, "description": m.description}
            for m in spec.modules.values()
        },
    }
    header = (
        GENERATED + "# Public module descriptions. Safe to show any user, including in\n"
        "# restricted-module refusals (CLAUDE.md rule 7). Must cover every module\n"
        "# in personas.yaml; startup aborts otherwise.\n"
    )
    return header + yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=1000)


def outputs(spec: Spec, personas: Path, catalogue: Path) -> dict[Path, str]:
    return {personas: render_personas(spec), catalogue: render_catalogue(spec)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "derive", "check"])
    parser.add_argument("--spec", type=Path, default=SPEC_PATH)
    parser.add_argument("--schema", type=Path, default=SCHEMA_PATH)
    parser.add_argument("--personas", type=Path, default=PERSONAS_PATH)
    parser.add_argument("--catalogue", type=Path, default=CATALOGUE_PATH)
    args = parser.parse_args(argv)

    try:
        spec = parse(load_raw(args.spec.read_text()), load_schema(args.schema))
    except SpecError as e:
        print(f"{args.spec}: invalid spec", file=sys.stderr)
        for err in e.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    files = outputs(spec, args.personas, args.catalogue)
    if args.command == "derive":
        for path, text in files.items():
            path.write_text(text)
            print(f"wrote {path}")
    elif args.command == "check":
        stale = [p for p, text in files.items() if not p.exists() or p.read_text() != text]
        if stale:
            for p in stale:
                print(f"{p} is out of date with {args.spec}; run `make spec`", file=sys.stderr)
            return 1
    personas = derive_personas(spec)
    print(
        f"spec ok: {len(spec.modules)} modules, {len(personas)} personas, "
        f"{len(spec.workflows)} workflows"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
