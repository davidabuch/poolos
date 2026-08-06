from __future__ import annotations

from datetime import datetime, timedelta, timezone

from poolos.execution_models import ExecutionStep
from poolos.execution_receipt import ExecutionReceipt, ExecutionReceiptDisposition
from poolos.homeassistant.observations import (
    HomeAssistantObservationBinding,
    HomeAssistantObservationProfile,
    HomeAssistantState,
    HomeAssistantValueType,
)
from poolos.integration import SetPumpSpeed
from poolos.observations import FreshnessPolicy
from poolos.post_delivery_observation_verification import (
    PostDeliveryObservationVerifier,
    PostDeliveryVerificationDisposition,
    PostDeliveryVerificationRequest,
)

NOW = datetime(2026, 8, 6, 5, 0, tzinfo=timezone.utc)


def _step() -> ExecutionStep:
    return ExecutionStep(
        step_id="step-pump-speed",
        sequence=1,
        operation=SetPumpSpeed(
            equipment_id="pool_filter_pump",
            rpm=2200,
            operation_id="operation-pump-speed",
        ),
        expected_observations={"pool_filter_pump_rpm": 2200},
    )


def _receipt(
    disposition: ExecutionReceiptDisposition = (
        ExecutionReceiptDisposition.COMPLETED
    ),
    *,
    step_id: str = "step-pump-speed",
    plan_id: str = "plan-pump-speed",
) -> ExecutionReceipt:
    return ExecutionReceipt(
        receipt_id="receipt-pump-speed",
        disposition=disposition,
        recorded_at=NOW,
        acknowledgement_id="ack-pump-speed",
        delivery_result_id="delivery-pump-speed",
        delivery_request_id="request-pump-speed",
        service_call_id="service-call-pump-speed",
        correlation_id="correlation-pump-speed",
        detail=(
            None
            if disposition is ExecutionReceiptDisposition.COMPLETED
            else "failed"
        ),
        provenance={
            "source_execution_step_id": step_id,
            "source_execution_plan_id": plan_id,
        },
    )


def _profile() -> HomeAssistantObservationProfile:
    return HomeAssistantObservationProfile(
        bindings=(
            HomeAssistantObservationBinding(
                entity_id="number.pool_filter_pump_rpm",
                observation_id="pool_filter_pump_rpm",
                value_type=HomeAssistantValueType.INTEGER,
            ),
        )
    )


def _state(
    value: str,
    *,
    observed_at: datetime = NOW + timedelta(seconds=2),
) -> HomeAssistantState:
    return HomeAssistantState(
        entity_id="number.pool_filter_pump_rpm",
        state=value,
        last_changed=observed_at,
        last_updated=observed_at,
    )


def _request(
    *,
    receipt: ExecutionReceipt | None = None,
    states: tuple[HomeAssistantState, ...] = (),
    evaluated_at: datetime = NOW + timedelta(seconds=3),
    plan_id: str = "plan-pump-speed",
) -> PostDeliveryVerificationRequest:
    return PostDeliveryVerificationRequest(
        receipt=receipt or _receipt(),
        plan_id=plan_id,
        step=_step(),
        observation_profile=_profile(),
        states=states,
        evaluated_at=evaluated_at,
        timeout=timedelta(seconds=15),
        freshness_policy=FreshnessPolicy(max_age=timedelta(seconds=10)),
    )


def test_matching_home_assistant_state_verifies_completed_delivery() -> None:
    result = PostDeliveryObservationVerifier().evaluate(
        _request(states=(_state("2200"),))
    )

    assert result.disposition is PostDeliveryVerificationDisposition.VERIFIED
    assert result.reason == "expected_state_observed"
    assert result.terminal
    assert result.verification is not None
    assert result.provenance["source_execution_receipt_id"] == "receipt-pump-speed"


def test_mismatched_state_is_classified_without_retry() -> None:
    result = PostDeliveryObservationVerifier().evaluate(
        _request(states=(_state("1800"),))
    )

    assert result.disposition is PostDeliveryVerificationDisposition.MISMATCHED
    assert result.reason == "observed_state_mismatch"
    assert result.terminal


def test_missing_state_is_pending_before_deadline() -> None:
    result = PostDeliveryObservationVerifier().evaluate(_request())

    assert result.disposition is PostDeliveryVerificationDisposition.PENDING
    assert not result.terminal


def test_missing_state_times_out_at_deadline() -> None:
    result = PostDeliveryObservationVerifier().evaluate(
        _request(evaluated_at=NOW + timedelta(seconds=15))
    )

    assert result.disposition is PostDeliveryVerificationDisposition.TIMED_OUT
    assert result.terminal


def test_unavailable_entity_is_classified_explicitly() -> None:
    result = PostDeliveryObservationVerifier().evaluate(
        _request(states=(_state("unavailable"),))
    )

    assert result.disposition is PostDeliveryVerificationDisposition.UNAVAILABLE
    assert result.reason == "entity_unavailable_or_unusable"
    assert not result.terminal


def test_stale_observation_is_classified_explicitly() -> None:
    stale = _state("2200", observed_at=NOW - timedelta(seconds=30))
    result = PostDeliveryObservationVerifier().evaluate(
        _request(states=(stale,), evaluated_at=NOW + timedelta(seconds=1))
    )

    assert result.disposition is PostDeliveryVerificationDisposition.STALE
    assert result.reason == "observation_stale"
    assert not result.terminal


def test_failed_delivery_receipt_is_rejected_before_observation_ingestion() -> None:
    result = PostDeliveryObservationVerifier().evaluate(
        _request(
            receipt=_receipt(ExecutionReceiptDisposition.FAILED),
            states=(_state("2200"),),
        )
    )

    assert result.disposition is PostDeliveryVerificationDisposition.REJECTED
    assert result.reason == "delivery_receipt_not_completed"
    assert result.verification is None
    assert result.terminal


def test_receipt_step_identity_mismatch_is_rejected() -> None:
    result = PostDeliveryObservationVerifier().evaluate(
        _request(receipt=_receipt(step_id="different-step"))
    )

    assert result.disposition is PostDeliveryVerificationDisposition.REJECTED
    assert result.reason == "receipt_step_identity_mismatch"


def test_receipt_plan_identity_mismatch_is_rejected() -> None:
    result = PostDeliveryObservationVerifier().evaluate(
        _request(receipt=_receipt(plan_id="different-plan"))
    )

    assert result.disposition is PostDeliveryVerificationDisposition.REJECTED
    assert result.reason == "receipt_plan_identity_mismatch"


def test_replay_preserves_deterministic_result_and_verification_identities() -> None:
    request = _request(states=(_state("2200"),))
    verifier = PostDeliveryObservationVerifier()

    first = verifier.evaluate(request)
    second = verifier.evaluate(request)

    assert first == second
    assert first.result_id == second.result_id
    assert first.verification == second.verification


def test_request_rejects_duplicate_entity_snapshots() -> None:
    state = _state("2200")
    try:
        _request(states=(state, state))
    except ValueError as exc:
        assert "unique entity IDs" in str(exc)
    else:
        raise AssertionError("duplicate entity snapshots should fail closed")
