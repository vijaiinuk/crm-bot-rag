from pathlib import Path
from typing import Any

import yaml

from chatbot.ports.entitlements import EntitlementError, Principal


class PersonaFileError(ValueError):
    """personas.yaml is malformed or names an unknown module. Loading aborts."""


class LocalEntitlementProvider:
    """Resolves entitlements from personas.yaml, keyed by `role@tenant`.

    The file is validated eagerly at construction: a bad file stops the app
    from starting rather than producing partial or allow-all entitlements.
    """

    def __init__(self, personas: dict[str, frozenset[str]]) -> None:
        self._personas = personas

    @classmethod
    def from_file(cls, path: Path) -> "LocalEntitlementProvider":
        try:
            raw = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError) as e:
            raise PersonaFileError(f"cannot read {path}: {e}") from e
        return cls(_parse(raw, source=str(path)))

    @property
    def persona_ids(self) -> frozenset[str]:
        return frozenset(self._personas)

    async def resolve(self, principal: Principal) -> frozenset[str]:
        persona_id = f"{principal.role}@{principal.tenant}"
        try:
            return self._personas[persona_id]
        except KeyError:
            raise EntitlementError(f"unknown persona {persona_id!r}") from None


def _parse(raw: Any, *, source: str) -> dict[str, frozenset[str]]:
    if not isinstance(raw, dict):
        raise PersonaFileError(f"{source}: expected a mapping")
    known = raw.get("known_modules")
    personas = raw.get("personas")
    if not isinstance(known, list) or not known or not all(isinstance(m, str) for m in known):
        raise PersonaFileError(f"{source}: known_modules must be a non-empty list of strings")
    if not isinstance(personas, dict) or not personas:
        raise PersonaFileError(f"{source}: personas must be a non-empty mapping")

    known_set = frozenset(known)
    out: dict[str, frozenset[str]] = {}
    for persona_id, modules in personas.items():
        if not isinstance(persona_id, str) or persona_id.count("@") != 1:
            raise PersonaFileError(f"{source}: persona id {persona_id!r} must be role@client")
        if not isinstance(modules, list) or not modules:
            raise PersonaFileError(f"{source}: {persona_id} needs a non-empty module list")
        unknown = set(modules) - known_set
        if unknown:
            raise PersonaFileError(f"{source}: {persona_id} has unknown modules {sorted(unknown)}")
        if "core" not in modules:
            raise PersonaFileError(f"{source}: {persona_id} must include `core`")
        out[persona_id] = frozenset(modules)
    return out
