from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ModuleDefinition:
    """Normalized representation of a single PHP module entry."""

    name: str
    enabled: bool
    priority: int
    content: Optional[str]
