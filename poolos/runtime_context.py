"""Immutable snapshots shared across a PoolOS runtime cycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping

from .events import PoolEvent


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    """Read-only view of the runtime at a specific point in one cycle.

    The context intentionally carries summaries and references that are safe for
    diagnostics and future extension points. It does not expose mutating
    methods and therefore cannot command hardware.
    """

    cycle_number: int
    observed_at: datetime
    runtime_status: str
    active_plan_ids: tuple[str, ...]
    pending_execution_count: int
    pending_reconciliation_count: int
    events: tuple[PoolEvent, ...] = ()
    metadata: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        if self.cycle_number < 1:
            raise ValueError("cycle_number must be at least one")
        if self.observed_at.tzinfo is None:
            raise ValueError("runtime context timestamp must be timezone-aware")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def with_metadata(self, **values: Any) -> "RuntimeContext":
        merged = dict(self.metadata)
        merged.update(values)
        return RuntimeContext(
            cycle_number=self.cycle_number,
            observed_at=self.observed_at,
            runtime_status=self.runtime_status,
            active_plan_ids=self.active_plan_ids,
            pending_execution_count=self.pending_execution_count,
            pending_reconciliation_count=self.pending_reconciliation_count,
            events=self.events,
            metadata=merged,
        )
