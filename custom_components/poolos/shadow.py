"""Home Assistant adapter for the PoolOS read-only shadow runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from poolos.shadow_runtime import (
    ShadowRuntime,
    ShadowRuntimeInput,
    ShadowRuntimeResult,
    observation_fingerprint,
)

from .observation import ObservationConcept, ObservationSnapshot


@dataclass(slots=True)
class HomeAssistantShadowRuntime:
    """Convert commissioned observations into non-actuating shadow evaluations."""

    runtime: ShadowRuntime

    @classmethod
    def create(cls) -> "HomeAssistantShadowRuntime":
        return cls(runtime=ShadowRuntime())

    @property
    def latest(self) -> ShadowRuntimeResult | None:
        return self.runtime.latest

    def evaluate(self, snapshot: ObservationSnapshot) -> ShadowRuntimeResult:
        facts = {item.observation_id: item.value for item in snapshot.observations}
        fingerprint = observation_fingerprint(
            generated_at=snapshot.generated_at,
            facts={key: facts[key] for key in sorted(facts)},
        )
        return self.runtime.evaluate(
            ShadowRuntimeInput(
                evaluated_at=snapshot.generated_at,
                pool_temperature=float(facts[ObservationConcept.POOL_TEMPERATURE.value]),
                pool_active=bool(facts[ObservationConcept.POOL_ACTIVE.value]),
                pump_rpm=int(facts[ObservationConcept.PUMP_RPM.value]),
                observation_healthy=snapshot.healthy,
                observation_fingerprint=fingerprint,
            )
        )

    def diagnostics(self) -> dict[str, Any] | None:
        latest = self.latest
        return None if latest is None else latest.diagnostics()
