from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from poolos.integration import ThermalBody
from poolos.thermal_automatic_execution import (
    ThermalAutomaticDriverState,
    ThermalAutomaticExecutionDriver,
)
from poolos.thermal_live_execution import (
    ThermalLiveExecutionContext,
    ThermalLiveExecutionOwnership,
)
from poolos.thermal_runtime_orchestration import ThermalRuntimeOrchestrator
from poolos.thermal_runtime_ownership import (
    ThermalRuntimeOwnershipDisposition,
    ThermalRuntimeOwnershipStatus,
)

NOW = datetime(2026, 10, 2, 18, 0, tzinfo=UTC)


def _owned_driver(*, established_at: datetime) -> ThermalAutomaticExecutionDriver:
    orchestrator = ThermalRuntimeOrchestrator()
    driver = ThermalAutomaticExecutionDriver(orchestrator)
    driver.set_enabled(True, changed_at=NOW, current_epoch_identity=None)

    ownership = ThermalLiveExecutionOwnership(
        evaluation_id="evaluation-1",
        thermal_plan_id="plan-1",
        execution_plan_id="execution-plan-1",
        target_body=ThermalBody.POOL,
        body_activation_operation_id="pool-body-op",
        body_activation_receipt_id="pool-body-receipt",
        body_activation_correlation_id="pool-body-correlation",
    )
    established = orchestrator.ownership.establish(
        ownership,
        established_at=established_at,
        requested_mode="Solar",
        current_context=ThermalLiveExecutionContext(
            "evaluation-1",
            "plan-1",
        ),
    )
    assert established.disposition is ThermalRuntimeOwnershipDisposition.ESTABLISHED
    return driver


def test_frame_before_current_ownership_boundary_is_ignored() -> None:
    established_at = NOW + timedelta(seconds=2)
    driver = _owned_driver(established_at=established_at)
    before = driver.assessment
    assert before is not None

    stale_frame = SimpleNamespace(
        epoch_identity="stale-after-accept",
        observed_at=NOW + timedelta(seconds=1),
    )

    result = asyncio.run(
        driver.process_epoch(
            stale_frame,  # type: ignore[arg-type]
            delivery_factory=None,  # type: ignore[arg-type]
        )
    )

    assert result is before
    lease = driver.orchestrator.ownership.state.lease
    assert lease is not None
    assert lease.status is ThermalRuntimeOwnershipStatus.OWNED
    assert lease.established_at == established_at


def test_fail_closed_never_retires_before_ownership_establishment() -> None:
    established_at = NOW + timedelta(seconds=2)
    driver = _owned_driver(established_at=established_at)

    failed = driver.fail_closed(
        failed_at=NOW + timedelta(seconds=1),
        reason="automatic_thermal_driver_exception:ValueError",
    )

    assert failed.state is ThermalAutomaticDriverState.FAILED
    lease = driver.orchestrator.ownership.state.lease
    assert lease is not None
    assert lease.status is ThermalRuntimeOwnershipStatus.RELINQUISHED
    assert lease.ended_at == established_at


def test_retire_session_clamps_to_current_lease_establishment() -> None:
    established_at = NOW + timedelta(seconds=3)
    driver = _owned_driver(established_at=established_at)

    driver._retire_session(
        at=NOW + timedelta(seconds=1),
        reason="orchestration_processing_failed",
    )

    lease = driver.orchestrator.ownership.state.lease
    assert lease is not None
    assert lease.status is ThermalRuntimeOwnershipStatus.RELINQUISHED
    assert lease.ended_at == established_at
