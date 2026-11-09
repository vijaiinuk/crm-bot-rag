from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Principal:
    """Identity taken from a verified JWT. Never built from request data."""

    sub: str
    tenant: str
    role: str


class EntitlementError(Exception):
    """Entitlements could not be resolved. Callers must deny, never allow-all."""


class EntitlementProvider(Protocol):
    async def resolve(self, principal: Principal) -> frozenset[str]:
        """Return the modules this principal may see. Raise EntitlementError to deny."""
        ...
