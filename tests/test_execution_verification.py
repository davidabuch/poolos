"""Tests for Epic 10.13G observation-based execution verification."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from poolos.execution_models import ExecutionStep, VerificationStatus
from poolos.execution_verification import (
    ExecutionVerificationEngine,
    ExecutionVerificationRequest,
    VerificationEvidenceDisposition,
)
from poolos.integration import StartPump
from poolos.observations import (
    FreshnessPolicy,
    ObservationQuality,
    ObservationSourceKind,
    ObservationStore,
    PoolObservation,
)


NOW = datetime(2026, 7, 31, 20, 0, tzinfo=timezone.utc)


def step(
    *,
    verification_required: bool = True,
    expected: dict[str, object] | None = None,
) -> ExecutionStep:
    return ExecutionStep(
        step_id="step-1",
        sequence=1,
        operation=StartPump(equipment_id="main-pump", operation_id="op-1"),
        verification_required=verification_required,
        expected_observations=(
            expected
            if expected is not None
            else {"pump.main-pump.running": True}
        ),
    )


def observation(
    observation_id: str,
    value: object,
    *,
    observed_at: datetime = NOW,
    quality: ObservationQuality = ObservationQuality.GOOD,
    confidence: float = 1.0,
    source_kind: ObservationSourceKind = ObservationSourceKind.SIMULATED,
) -> PoolObservation:
    return PoolObservation(
        observation_id=observation_id,
        value=value,
        observed_at=observed_at,
        source_kind=source_kind,
        source_id="simulator-1",
        quality=quality,
        confidence=confidence,
    )


def request(
    execution_step: ExecutionStep,
    store: ObservationStore,
    *,
    evaluated_at: datetime = NOW,
    timeout: timedelta = timedelta(seconds=30),
) -> ExecutionVerificationRequest:
    return ExecutionVerificationRequest(
        plan_id="plan-1",
        step=execution_step,
        observations=store,
        verification_started_at=NOW - timedelta(seconds=5),
        evaluated_at=evaluated_at,
        timeout=timeout,
        freshness_policy=FreshnessPolicy(max_age=timedelta(seconds=15)),
        source_id="simulator-1",
    )


def test_matching_fresh_observation_is_verified() -> None:
    store = ObservationStore()
    store.put(observation("pump.main-pump.running", True))

    result = ExecutionVerificationEngine().verify(request(step(), store))

    assert result.status is VerificationStatus.VERIFIED
    assert result.reason == "all_expected_observations_verified"
    assert result.terminal
    assert result.evidence[0].disposition is VerificationEvidenceDisposition.MATCHED


def test_nonmatching_fresh_observation_fails_before_timeout() -> None:
    store = ObservationStore()
    store.put(observation("pump.main-pump.running", False))

    result = ExecutionVerificationEngine().verify(request(step(), store))

    assert result.status is VerificationStatus.FAILED
    assert result.reason == "fresh_observations_do_not_match_expectations"
    assert result.evidence[0].disposition is VerificationEvidenceDisposition.MISMATCHED


def test_missing_evidence_is_pending_before_deadline() -> None:
    result = ExecutionVerificationEngine().verify(request(step(), ObservationStore()))

    assert result.status is VerificationStatus.PENDING
    assert not result.terminal
    assert result.evidence[0].disposition is VerificationEvidenceDisposition.MISSING


def test_some_verified_and_some_missing_is_partial() -> None:
    store = ObservationStore()
    store.put(observation("pump.main-pump.running", True))
    execution_step = step(
        expected={
            "pump.main-pump.running": True,
            "pump.main-pump.speed_rpm": 1800,
        }
    )

    result = ExecutionVerificationEngine().verify(request(execution_step, store))

    assert result.status is VerificationStatus.PARTIAL
    assert not result.terminal
    assert [item.disposition for item in result.evidence] == [
        VerificationEvidenceDisposition.MATCHED,
        VerificationEvidenceDisposition.MISSING,
    ]


def test_unverified_result_times_out_at_deadline() -> None:
    execution_step = step()
    verification_request = request(
        execution_step,
        ObservationStore(),
        evaluated_at=NOW + timedelta(seconds=25),
        timeout=timedelta(seconds=20),
    )

    result = ExecutionVerificationEngine().verify(verification_request)

    assert result.status is VerificationStatus.TIMED_OUT
    assert result.terminal
    assert result.reason == "verification_deadline_reached"


def test_verification_not_required_returns_without_evidence() -> None:
    result = ExecutionVerificationEngine().verify(
        request(step(verification_required=False, expected={}), ObservationStore())
    )

    assert result.status is VerificationStatus.NOT_REQUIRED
    assert result.evidence == ()
    assert result.terminal


def test_stale_observation_cannot_verify() -> None:
    store = ObservationStore()
    store.put(
        observation(
            "pump.main-pump.running",
            True,
            observed_at=NOW - timedelta(minutes=1),
        )
    )

    result = ExecutionVerificationEngine().verify(request(step(), store))

    assert result.status is VerificationStatus.PENDING
    assert result.evidence[0].disposition is VerificationEvidenceDisposition.STALE


def test_future_observation_cannot_verify() -> None:
    store = ObservationStore()
    store.put(
        observation(
            "pump.main-pump.running",
            True,
            observed_at=NOW + timedelta(seconds=1),
        )
    )

    result = ExecutionVerificationEngine().verify(request(step(), store))

    assert result.status is VerificationStatus.PENDING
    assert result.evidence[0].disposition is VerificationEvidenceDisposition.FUTURE


def test_unaccepted_quality_and_low_confidence_are_unresolved() -> None:
    bad_quality = ObservationStore()
    bad_quality.put(
        observation(
            "pump.main-pump.running",
            True,
            quality=ObservationQuality.INVALID,
        )
    )
    low_confidence = ObservationStore()
    low_confidence.put(
        observation("pump.main-pump.running", True, confidence=0.2)
    )

    bad_result = ExecutionVerificationEngine().verify(request(step(), bad_quality))
    low_result = ExecutionVerificationEngine().verify(
        request(step(), low_confidence)
    )

    assert bad_result.evidence[0].disposition is VerificationEvidenceDisposition.UNUSABLE
    assert (
        low_result.evidence[0].disposition
        is VerificationEvidenceDisposition.LOW_CONFIDENCE
    )


def test_live_observation_does_not_satisfy_simulation_verification() -> None:
    store = ObservationStore()
    store.put(
        observation(
            "pump.main-pump.running",
            True,
            source_kind=ObservationSourceKind.LIVE,
        )
    )

    result = ExecutionVerificationEngine().verify(request(step(), store))

    assert result.status is VerificationStatus.PENDING
    assert result.evidence[0].disposition is VerificationEvidenceDisposition.MISSING


def test_verification_id_is_deterministic_for_identical_evidence_snapshot() -> None:
    store = ObservationStore()
    store.put(observation("pump.main-pump.running", True))
    engine = ExecutionVerificationEngine()
    verification_request = request(step(), store)

    first = engine.verify(verification_request)
    second = engine.verify(verification_request)

    assert first == second
    assert first.verification_id == second.verification_id


def test_result_and_evidence_are_immutable_snapshots() -> None:
    mutable_value = {"running": True, "speeds": [1800]}
    store = ObservationStore()
    store.put(observation("pump.main-pump.state", mutable_value))
    execution_step = step(expected={"pump.main-pump.state": mutable_value})

    result = ExecutionVerificationEngine().verify(request(execution_step, store))
    mutable_value["running"] = False
    mutable_value["speeds"].append(2200)  # type: ignore[union-attr]

    assert result.evidence[0].actual_value["running"] is True
    assert result.evidence[0].actual_value["speeds"] == (1800,)
    with pytest.raises(FrozenInstanceError):
        result.reason = "changed"  # type: ignore[misc]


def test_request_validates_time_and_policy_inputs() -> None:
    with pytest.raises(ValueError, match="cannot precede"):
        ExecutionVerificationRequest(
            plan_id="plan-1",
            step=step(),
            observations=ObservationStore(),
            verification_started_at=NOW,
            evaluated_at=NOW - timedelta(seconds=1),
            timeout=timedelta(seconds=30),
            freshness_policy=FreshnessPolicy(max_age=timedelta(seconds=15)),
        )

    with pytest.raises(ValueError, match="must not be negative"):
        ExecutionVerificationRequest(
            plan_id="plan-1",
            step=step(),
            observations=ObservationStore(),
            verification_started_at=NOW,
            evaluated_at=NOW,
            timeout=timedelta(seconds=-1),
            freshness_policy=FreshnessPolicy(max_age=timedelta(seconds=15)),
        )


def test_verification_engine_has_no_delivery_collaborator() -> None:
    fields = getattr(ExecutionVerificationEngine, "__dataclass_fields__")

    assert set(fields) == {"verification_id_prefix"}
