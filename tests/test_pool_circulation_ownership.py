from __future__ import annotations

from datetime import UTC, datetime, timedelta

from poolos.pool_circulation_ownership import (
    PoolCirculationOwner,
    PoolCirculationOwnershipRegistry,
)
from poolos.thermal_runtime_ownership import (
    ThermalRuntimeConceptProvenance,
    ThermalRuntimeOwnedConcept,
)

NOW = datetime(2026, 9, 8, 16, 0, tzinfo=UTC)


def _provenance(
    concept: ThermalRuntimeOwnedConcept,
    value: bool | int,
) -> ThermalRuntimeConceptProvenance:
    return ThermalRuntimeConceptProvenance(
        concept=concept,
        operation_id=f"{concept.value}-operation",
        receipt_id=f"{concept.value}-receipt",
        correlation_id=f"{concept.value}-correlation",
        intended_value=value,
    )


def _filtration_owner() -> PoolCirculationOwnershipRegistry:
    registry = PoolCirculationOwnershipRegistry()
    registry.begin_epoch("epoch-1")
    registry.record_filtration_delivery(
        session_id="filtration-1",
        pool_pump_circuit_id="p0102",
        accepted_at=NOW,
        provenance=_provenance(ThermalRuntimeOwnedConcept.BODY_ACTIVATION, True),
    )
    registry.record_filtration_delivery(
        session_id="filtration-1",
        pool_pump_circuit_id="p0102",
        accepted_at=NOW + timedelta(seconds=1),
        provenance=_provenance(ThermalRuntimeOwnedConcept.PUMP_SETPOINT, 2600),
    )
    registry.confirm_filtration_body(
        session_id="filtration-1",
        confirmed_at=NOW + timedelta(seconds=2),
    )
    registry.confirm_filtration(
        session_id="filtration-1",
        confirmed_at=NOW + timedelta(seconds=3),
    )
    return registry


def test_filtration_to_thermal_handoff_is_explicit_and_preserves_only_body_provenance() -> None:
    registry = _filtration_owner()
    registry.begin_epoch("epoch-2")
    assert registry.reserve_thermal("epoch-2")
    handoff = registry.begin_filtration_to_thermal(
        thermal_purpose_id="solar-purpose",
        established_at=NOW + timedelta(seconds=3),
    )
    assert handoff is not None
    assert handoff.body_activation.intended_value is True
    assert registry.owner is PoolCirculationOwner.FILTRATION_TO_THERMAL
    registry.complete_filtration_to_thermal(
        token_id=handoff.token_id,
        thermal_lease_id="thermal-lease",
    )
    assert registry.owner is PoolCirculationOwner.THERMAL
    assert registry.filtration_lease is None


def test_accepted_operations_remain_acquiring_until_body_and_pump_are_verified() -> None:
    registry = PoolCirculationOwnershipRegistry()
    registry.begin_epoch("epoch-1")
    registry.record_filtration_delivery(
        session_id="filtration-1",
        pool_pump_circuit_id="p0102",
        accepted_at=NOW,
        provenance=_provenance(ThermalRuntimeOwnedConcept.BODY_ACTIVATION, True),
    )
    assert registry.owner is PoolCirculationOwner.FILTRATION_ACQUIRING
    assert registry.begin_filtration_to_thermal(
        thermal_purpose_id="thermal-purpose",
        established_at=NOW + timedelta(seconds=1),
    ) is None

    registry.confirm_filtration_body(
        session_id="filtration-1",
        confirmed_at=NOW + timedelta(seconds=1),
    )
    registry.record_filtration_delivery(
        session_id="filtration-1",
        pool_pump_circuit_id="p0102",
        accepted_at=NOW + timedelta(seconds=2),
        provenance=_provenance(ThermalRuntimeOwnedConcept.PUMP_SETPOINT, 2600),
    )
    assert registry.owner is PoolCirculationOwner.FILTRATION_ACQUIRING
    registry.confirm_filtration(
        session_id="filtration-1",
        confirmed_at=NOW + timedelta(seconds=3),
    )
    assert registry.owner is PoolCirculationOwner.FILTRATION


def test_handoff_cancel_restores_filtration_but_post_delivery_invalidation_owns_nothing() -> None:
    cancelled = _filtration_owner()
    cancelled.begin_epoch("epoch-2")
    assert cancelled.reserve_thermal("epoch-2")
    token = cancelled.begin_filtration_to_thermal(
        thermal_purpose_id="thermal-purpose",
        established_at=NOW + timedelta(seconds=4),
    )
    assert token is not None
    cancelled.cancel_filtration_to_thermal(token_id=token.token_id)
    assert cancelled.owner is PoolCirculationOwner.FILTRATION
    assert cancelled.filtration_lease is not None

    invalidated = _filtration_owner()
    invalidated.begin_epoch("epoch-2")
    assert invalidated.reserve_thermal("epoch-2")
    token = invalidated.begin_filtration_to_thermal(
        thermal_purpose_id="thermal-purpose",
        established_at=NOW + timedelta(seconds=4),
    )
    assert token is not None
    invalidated.invalidate_filtration_to_thermal(token_id=token.token_id)
    assert invalidated.owner is PoolCirculationOwner.NONE
    assert invalidated.filtration_lease is None


def test_hardware_state_has_no_api_that_can_manufacture_ownership() -> None:
    registry = PoolCirculationOwnershipRegistry()
    registry.begin_epoch("epoch-1")
    assert registry.owner is PoolCirculationOwner.NONE
    assert registry.filtration_lease is None


def test_thermal_reservation_is_exactly_one_authoritative_epoch() -> None:
    registry = PoolCirculationOwnershipRegistry()
    registry.begin_epoch("epoch-1")
    assert registry.reserve_thermal("epoch-1")
    assert registry.thermal_reserved_for("epoch-1")
    registry.begin_epoch("epoch-2")
    assert not registry.thermal_reserved_for("epoch-1")
    assert not registry.thermal_reserved_for("epoch-2")


def test_thermal_to_filtration_requires_explicit_body_and_new_pump_provenance() -> None:
    registry = PoolCirculationOwnershipRegistry()
    registry.mark_thermal_owned("thermal-lease")
    lease = registry.accept_thermal_to_filtration(
        session_id="thermal-successor",
        pool_pump_circuit_id="p0102",
        accepted_at=NOW,
        body_activation=_provenance(
            ThermalRuntimeOwnedConcept.BODY_ACTIVATION,
            True,
        ),
        pump_setpoint=_provenance(
            ThermalRuntimeOwnedConcept.PUMP_SETPOINT,
            2600,
        ),
    )
    assert lease.verified
    assert registry.owner is PoolCirculationOwner.FILTRATION
    assert registry.thermal_lease_id is None


def test_restart_unload_reconstructs_nothing() -> None:
    registry = _filtration_owner()
    registry.unload()
    assert registry.owner is PoolCirculationOwner.NONE
    assert registry.filtration_lease is None
    assert registry.handoff is None
