from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModuleInfo:
    name: str
    display_name: str
    description: str
    keywords: tuple[str, ...] = ()  # public UI labels and entity names

    @property
    def profile(self) -> str:
        """Public text describing the module: what a restricted-module match is scored on."""
        words = f" Terms: {', '.join(self.keywords)}." if self.keywords else ""
        return f"{self.display_name}: {self.description}{words}"


@dataclass(frozen=True, slots=True)
class ModuleCatalogue:
    """Public, non-restricted facts about modules: safe to show any user.

    Loaded from YAML locally; from the `module_catalogue` table later.
    """

    modules: Mapping[str, ModuleInfo]
    restricted_contact: str

    def display_name(self, module: str) -> str:
        return self.modules[module].display_name
