"""Exact HA adapter for confirmed-grid-outage reduction candidates."""

from __future__ import annotations

from dataclasses import dataclass

from poolos.grid_outage_physical_safety import GridOutageReductionCandidate
from poolos.physical_command_authority import (
    GridOutageDispatchContext,
    PhysicalRequestSource,
)

from .manual_intellicenter import ManualIntelliCenterControl


@dataclass(frozen=True, slots=True)
class ManualIntelliCenterGridOutageDelivery:
    """Route only a pre-authorized exact outage candidate to the shared gateway."""

    manual: ManualIntelliCenterControl
    context: GridOutageDispatchContext

    async def deliver(self, candidate: GridOutageReductionCandidate) -> None:
        authority = self.context.authority
        if (
            candidate.candidate_id != authority.candidate_id
            or candidate.operation != authority.operation
            or candidate.target != authority.target
            or candidate.requested_value != authority.requested_value
        ):
            raise ValueError("outage delivery candidate does not match authorization")
        kwargs = {
            "request_source": PhysicalRequestSource.GRID_OUTAGE_SAFETY,
            "grid_outage_context": self.context,
        }
        if candidate.operation == "body_heat_source":
            assert isinstance(candidate.requested_value, str)
            await self.manual.async_set_body_heat_source(
                candidate.target, candidate.requested_value, **kwargs
            )
            return
        if candidate.operation == "body_active":
            if type(candidate.requested_value) is not bool:
                raise ValueError("outage body value must be boolean")
            await self.manual.async_set_body_active(
                candidate.target, candidate.requested_value, **kwargs
            )
            return
        if candidate.operation == "circuit_active":
            if type(candidate.requested_value) is not bool:
                raise ValueError("outage circuit value must be boolean")
            await self.manual.async_set_circuit_state(
                candidate.target, candidate.requested_value, **kwargs
            )
            return
        if candidate.operation == "pump_circuit_speed":
            if type(candidate.requested_value) is not int:
                raise ValueError("outage pump value must be an exact integer")
            await self.manual.async_set_pump_circuit_speed(
                candidate.target, candidate.requested_value, **kwargs
            )
            return
        raise ValueError("unsupported outage delivery operation")


__all__ = ["ManualIntelliCenterGridOutageDelivery"]
