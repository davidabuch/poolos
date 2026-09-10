"""Home Assistant composition for the command-free pump session runtime."""

from __future__ import annotations

from datetime import datetime, timedelta
from dataclasses import dataclass

from poolos.clock import FixedClock
from poolos.external_change import ExternalChangeBatch
from poolos.intellicenter_readonly import (
    NativeBodyKind,
    NativeIntelliCenterObservationSnapshot,
    NativeIntelliCenterTransportSnapshot,
    POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
    SPA_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
    resolve_body_pump_circuit,
)
from poolos.observations import (
    FreshnessPolicy,
    ObservationFreshness,
    ObservationQuality,
    ObservationSourceKind,
    PoolObservation,
)
from poolos.pump_speed_session import (
    PumpSpeedNativeTransition,
    PumpSpeedSessionBody,
    PumpSpeedSessionEvidence,
    PumpSpeedSessionPurpose,
    PumpSpeedSessionRuntime,
)
from poolos.physical_command_authority import PoolOSPhysicalCommandAuthority
from poolos.thermal_operating_purpose import (
    ThermalOperatingPurpose,
    ThermalOperatingPurposeEvidence,
    assess_thermal_operating_purpose,
)
from poolos.integration import PhysicalHeatMode, ThermalBody


_MINIMUM_CONFIDENCE = 0.5
_ACCEPTED_QUALITIES = (ObservationQuality.GOOD, ObservationQuality.DEGRADED)
_FRESHNESS = FreshnessPolicy(max_age=timedelta(seconds=30))


@dataclass(slots=True)
class PoolOSPumpSpeedSessionRuntime:
    """Translate authoritative HA/native frames into one core session runtime."""

    session: PumpSpeedSessionRuntime
    authority: PoolOSPhysicalCommandAuthority

    def synchronize(
        self,
        native: NativeIntelliCenterObservationSnapshot,
        transport: NativeIntelliCenterTransportSnapshot,
        *,
        connection_generation: int,
        probe_active: bool = False,
        priming_active: bool = False,
        outage_active: bool = False,
    ) -> None:
        by_id = {item.observation_id: item for item in native.observations}
        controller_mode = _usable_string(
            by_id.get("intellicenter.system_mode"), native.generated_at
        )
        if controller_mode != "auto":
            self.session.reset_currentness("controller_mode_not_current_auto")
            self.synchronize_authority()
            return
        pool_active = _usable_boolean(by_id.get("pool.active"), native.generated_at)
        spa_active = _usable_boolean(by_id.get("spa.active"), native.generated_at)
        body: PumpSpeedSessionBody | None
        if pool_active is True and spa_active is False:
            body = PumpSpeedSessionBody.POOL
        elif spa_active is True and pool_active is False:
            body = PumpSpeedSessionBody.HOT_TUB
        else:
            body = None
        if body is None:
            self.session.observe(
                PumpSpeedSessionEvidence(
                    observed_at=native.generated_at,
                    body=None,
                    purpose=None,
                    pump_circuit_id=None,
                    configured_speed_rpm=None,
                    connection_generation=connection_generation,
                    evidence_usable=pool_active is not None and spa_active is not None,
                )
            )
            self.synchronize_authority()
            return
        native_body = (
            NativeBodyKind.POOL
            if body is PumpSpeedSessionBody.POOL
            else NativeBodyKind.SPA
        )
        identity = resolve_body_pump_circuit(transport, body=native_body)
        concept = (
            POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT
            if body is PumpSpeedSessionBody.POOL
            else SPA_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT
        )
        configured = _usable_integer(by_id.get(concept), native.generated_at)
        purpose = self._purpose(
            body,
            by_id,
            probe_active=probe_active,
            priming_active=priming_active,
            outage_active=outage_active,
            evaluated_at=native.generated_at,
        )
        self.session.observe(
            PumpSpeedSessionEvidence(
                observed_at=native.generated_at,
                body=body,
                purpose=purpose,
                pump_circuit_id=None if identity is None else identity.native_id,
                configured_speed_rpm=configured,
                connection_generation=connection_generation,
                evidence_usable=(
                    purpose is not None and identity is not None and configured is not None
                ),
            )
        )
        self.synchronize_authority()

    def apply_external_changes(
        self,
        batch: ExternalChangeBatch,
        native: NativeIntelliCenterObservationSnapshot,
    ) -> None:
        """Consume ADR-107 output only after synchronize() applied boundaries."""

        state = self.session.snapshot
        if not state.active or state.pump_circuit_id is None or state.body is None:
            return
        concept = (
            POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT
            if state.body is PumpSpeedSessionBody.POOL
            else SPA_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT
        )
        correlations = {
            item.request_id: item
            for item in batch.correlated_consequences
            if item.operation == "pump_circuit_speed"
            and item.target == state.pump_circuit_id
        }
        for event in batch.events:
            if (
                event.concept != concept
                or event.native_object_id != state.pump_circuit_id
                or type(event.previous_value) not in {int, float}
                or type(event.new_value) not in {int, float}
                or float(event.previous_value) != float(round(float(event.previous_value)))
                or float(event.new_value) != float(round(float(event.new_value)))
            ):
                continue
            self.session.apply_transition(
                PumpSpeedNativeTransition(
                    concept=concept,
                    native_object_id=state.pump_circuit_id,
                    previous_rpm=int(round(float(event.previous_value))),
                    new_rpm=int(round(float(event.new_value))),
                    observed_at=event.observed_at,
                )
            )
        current = next(
            (item for item in native.observations if item.observation_id == concept),
            None,
        )
        current_rpm = _usable_integer(current, native.generated_at)
        if current_rpm is None:
            self.synchronize_authority()
            return
        for request_id in correlations:
            # Correlated consequences are intentionally not external events.
            # The exact current configured SPEED completes only the current
            # pending request; stale/superseded request IDs are ignored by core.
            self.session.apply_transition(
                PumpSpeedNativeTransition(
                    concept=concept,
                    native_object_id=state.pump_circuit_id,
                    previous_rpm=current_rpm,
                    new_rpm=current_rpm,
                    observed_at=native.generated_at,
                    correlated_request_id=request_id,
                )
            )
        self.synchronize_authority()

    def synchronize_authority(self) -> None:
        state = self.session.snapshot
        if not state.evidence_usable:
            self.authority.synchronize_pump_speed_session(
                session_id=None,
                body=None,
                purpose=None,
                pump_circuit_id=None,
                effective_rpm=None,
            )
            return
        self.authority.synchronize_pump_speed_session(
            session_id=state.session_id,
            body=None if state.body is None else state.body.value,
            purpose=None if state.purpose is None else state.purpose.value,
            pump_circuit_id=state.pump_circuit_id,
            effective_rpm=state.effective_rpm,
        )

    def _purpose(
        self,
        body: PumpSpeedSessionBody,
        observations: dict[str, PoolObservation],
        *,
        probe_active: bool,
        priming_active: bool,
        outage_active: bool,
        evaluated_at: datetime,
    ) -> PumpSpeedSessionPurpose | None:
        if outage_active:
            return PumpSpeedSessionPurpose.GRID_OUTAGE
        if priming_active:
            return PumpSpeedSessionPurpose.PRIMING
        if probe_active:
            return PumpSpeedSessionPurpose.TEMPERATURE_PROBE
        prefix = "pool" if body is PumpSpeedSessionBody.POOL else "spa"
        other = "spa" if prefix == "pool" else "pool"
        required = tuple(
            observations.get(concept)
            for concept in (
                f"{prefix}.active",
                f"{other}.active",
                f"{prefix}.raw_heater_id",
                "solar.active",
                "heater.active",
                *(
                    ("spa.heating_demand_active",)
                    if prefix == "spa"
                    else ()
                ),
            )
        )
        selected = _source(_value(observations.get(f"{prefix}.raw_heater_id")))
        usable = (
            selected is not None
            and all(item is not None and _usable(item, evaluated_at) for item in required)
        )
        assessment = assess_thermal_operating_purpose(
            ThermalOperatingPurposeEvidence(
                body=(
                    ThermalBody.POOL
                    if body is PumpSpeedSessionBody.POOL
                    else ThermalBody.HOT_TUB
                ),
                body_active=_usable_boolean(observations.get(f"{prefix}.active"), evaluated_at),
                other_body_active=_usable_boolean(observations.get(f"{other}.active"), evaluated_at),
                selected_source=selected,
                solar_active=_usable_boolean(observations.get("solar.active"), evaluated_at),
                heater_active=_usable_boolean(observations.get("heater.active"), evaluated_at),
                body_heating_demand_active=(
                    _usable_boolean(observations.get("spa.heating_demand_active"), evaluated_at)
                    if prefix == "spa"
                    else _usable_boolean(observations.get("heater.active"), evaluated_at)
                ),
                evidence_usable=usable,
            ),
            baselines=self.session.baselines,
        )
        return {
            ThermalOperatingPurpose.ORDINARY_CIRCULATION: PumpSpeedSessionPurpose.ORDINARY,
            ThermalOperatingPurpose.SOLAR_HEATING: PumpSpeedSessionPurpose.SOLAR,
            ThermalOperatingPurpose.GAS_HEATING: PumpSpeedSessionPurpose.GAS,
        }.get(assessment.purpose)


def _usable(item: PoolObservation, evaluated_at: datetime) -> bool:
    return (
        item.source_kind is ObservationSourceKind.LIVE
        and item.quality in _ACCEPTED_QUALITIES
        and item.confidence >= _MINIMUM_CONFIDENCE
        and item.observed_at is not None
        and item.freshness(clock=FixedClock(evaluated_at), policy=_FRESHNESS)
        is ObservationFreshness.FRESH
    )


def _value(item: PoolObservation | None) -> object:
    return None if item is None else item.value


def _usable_boolean(item: PoolObservation | None, evaluated_at: datetime) -> bool | None:
    if item is None or not _usable(item, evaluated_at) or not isinstance(item.value, bool):
        return None
    return item.value


def _usable_integer(item: PoolObservation | None, evaluated_at: datetime) -> int | None:
    if item is None or not _usable(item, evaluated_at) or isinstance(item.value, bool):
        return None
    if not isinstance(item.value, (int, float)):
        return None
    value = float(item.value)
    return int(value) if value > 0 and value == float(int(value)) else None


def _usable_string(item: PoolObservation | None, evaluated_at: datetime) -> str | None:
    if item is None or not _usable(item, evaluated_at) or not isinstance(item.value, str):
        return None
    return item.value.strip().lower()


def _source(value: object) -> PhysicalHeatMode | None:
    return {
        "00000": PhysicalHeatMode.OFF,
        "H0001": PhysicalHeatMode.GAS,
        "H0002": PhysicalHeatMode.SOLAR,
    }.get(value)


__all__ = ["PoolOSPumpSpeedSessionRuntime"]
