from pathlib import Path
from typing import Any

import yaml

from chatbot.ports.catalogue import ModuleCatalogue, ModuleInfo


class CatalogueFileError(ValueError):
    """module_catalogue.yaml is malformed. Loading aborts."""


def load_catalogue(path: Path) -> ModuleCatalogue:
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as e:
        raise CatalogueFileError(f"cannot read {path}: {e}") from e
    return _parse(raw, source=str(path))


def _parse(raw: Any, *, source: str) -> ModuleCatalogue:
    if not isinstance(raw, dict):
        raise CatalogueFileError(f"{source}: expected a mapping")
    contact = raw.get("restricted_contact")
    modules = raw.get("modules")
    if not isinstance(contact, str) or not contact.strip():
        raise CatalogueFileError(f"{source}: restricted_contact must be a non-empty string")
    if not isinstance(modules, dict) or not modules:
        raise CatalogueFileError(f"{source}: modules must be a non-empty mapping")

    out: dict[str, ModuleInfo] = {}
    for name, entry in modules.items():
        if not isinstance(entry, dict):
            raise CatalogueFileError(f"{source}: module {name!r} must be a mapping")
        display = entry.get("display_name")
        description = entry.get("description")
        if not isinstance(display, str) or not display.strip():
            raise CatalogueFileError(f"{source}: module {name!r} needs a display_name")
        if not isinstance(description, str) or not description.strip():
            raise CatalogueFileError(f"{source}: module {name!r} needs a description")
        keywords = entry.get("keywords", [])
        if not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords):
            raise CatalogueFileError(f"{source}: module {name!r} keywords must be strings")
        out[str(name)] = ModuleInfo(
            name=str(name), display_name=display, description=description, keywords=tuple(keywords)
        )
    return ModuleCatalogue(modules=out, restricted_contact=contact)


def check_covers(catalogue: ModuleCatalogue, modules: frozenset[str]) -> None:
    """Every module a persona can hold must be describable in a refusal."""
    missing = modules - catalogue.modules.keys()
    if missing:
        raise CatalogueFileError(f"module catalogue has no entry for {sorted(missing)}")
