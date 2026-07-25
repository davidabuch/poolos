"""Configuration owned by one PoolOS kernel instance."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PoolOSConfig:
    """Stable installation-level kernel configuration."""

    installation_id: str = "default"
    installation_name: str = "PoolOS"
    emit_unchanged_state_events: bool = False

    def __post_init__(self) -> None:
        if not self.installation_id.strip():
            raise ValueError("installation_id must not be empty")
        if not self.installation_name.strip():
            raise ValueError("installation_name must not be empty")
