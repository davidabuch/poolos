from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from poolos.execution_models import ExecutionStep
from poolos.execution_receipt import ExecutionReceipt, ExecutionReceiptDisposition
from poolos.execution_reconciliation_planning import (
    ExecutionReconciliationDisposition,
    ExecutionReconciliationPlanner,
    ExecutionReconciliationRequest,
)
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
    PostDeliveryVerificationResult,
)
from poolos.recovery_coordinator import (
    RecoveryCoordinationRequest,
    RecoveryCoordinator,
    RecoveryDirective,
    RecoveryDirectiveDisposition,
    RecoveryPolicy,
)

NOW = datetime(2026, 8, 6, 8, 0, tzinfo=timezone.utc)
PLAN_ID = "plan-pump-speed"
STEP_ID = "step-pump-speed"
RECEIPT_ID = "receipt-pump-speed"
CORRELATION_ID = "correlation-pump-speed"


@dataclass(frozen=True, slots=True)
class HardenedScenarioOutcome:
    verification: PostDeliveryVerificationResult
    reconciliation_disposition: ExecutionReconciliationDisposition
    directive: RecoveryDirective


def _step() -> ExecutionStep:
    return ExecutionStep(
        step_id=STEP_ID,
        sequence=1,
        operation=SetPumpSpeed(
            equipment_id="pool_filter_pump",
            rpm=2200,
            operation_id="operation-pump-speed",
        ),
        expected_observations={"pool_filter_pump_rpm": 2200},
    )


def _receipt(
    disposition: ExecutionReceiptDisposition = ExecutionReceiptDisposition.COMPLETED,
    *,
    step_id: str = STEP_ID,
    plan_id: str = PLAN_ID,
) -> ExecutionReceipt:
    return ExecutionReceipt(
        receipt_id=RECEIPT_ID,
        disposition=disposition,
        recorded_at=NOW,
        acknowledgement_id="ack-pump-speed",
        delivery_result_id="delivery-pump-speed",
        delivery_request_id="request-pump-speed",
        service_call_id="service-call-pump-speed",
        correlation_id=CORRELATION_ID,
        detail=None if disposition is ExecutionReceiptDisposition.COMPLETED else "failed",
        provenance={
            "source_execution_step_id": step_id,
            "source_execution_plan_id": plan_id,
            "source_operational_action_id": "action-pump-speed",
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


def _run_scenario(
    *,
    receipt: ExecutionReceipt | None = None,
    states: tuple[HomeAssistantState, ...] = (),
    verification_time: datetime = NOW + timedelta(seconds=3),
    assumptions_current: bool = True,
    retry_allowed: bool = False,
    mismatch_persistent: bool = False,
    policy: RecoveryPolicy | None = None,
) -> HardenedScenarioOutcome:
    verification = PostDeliveryObservationVerifier().evaluate(
        PostDeliveryVerificationRequest(
            receipt=receipt or _receipt(),
            plan_id=PLAN_ID,
            step=_step(),
            observation_profile=_profile(),
            states=states,
            evaluated_at=verification_time,
            timeout=timedelta(seconds=15),
            freshness_policy=FreshnessPolicy(max_age=timedelta(seconds=10)),
            metadata={"scenario": "architecture_hardening"},
        )
    )
    reconciliation = ExecutionReconciliationPlanner().evaluate(
        ExecutionReconciliationRequest(
            verification_result=verification,
            evaluated_at=verification_time + timedelta(seconds=1),
            assumptions_current=assumptions_current,
            retry_allowed=retry_allowed,
            mismatch_persistent=mismatch_persistent,
            metadata={"policy_id": "reconciliation-policy-1"},
        )
    )
    directive = RecoveryCoordinator().coordinate(
        RecoveryCoordinationRequest(
            reconciliation_result=reconciliation,
            policy=policy
            or RecoveryPolicy(
                policy_id="recovery-policy-safe-default",
                allow_reevaluation_request=True,
                allow_retry_request=False,
                allow_operator_intervention_request=True,
            ),
            coordinated_at=verification_time + timedelta(seconds=2),
            metadata={"scenario": "architecture_hardening"},
        )
    )
    return HardenedScenarioOutcome(
        verification=verification,
        reconciliation_disposition=reconciliation.disposition,
        directive=directive,
    )


def test_full_success_path_is_satisfied_and_requires_no_recovery() -> None:
    outcome = _run_scenario(states=(_state("2200"),))

    assert outcome.verification.disposition is PostDeliveryVerificationDisposition.VERIFIED
    assert outcome.reconciliation_disposition is ExecutionReconciliationDisposition.SATISFIED
    assert outcome.directive.disposition is RecoveryDirectiveDisposition.NO_ACTION
    assert not outcome.directive.requires_follow_up


def test_timeout_can_be_recommended_and_policy_authorized_for_later_retry() -> None:
    outcome = _run_scenario(
        verification_time=NOW + timedelta(seconds=15),
        retry_allowed=True,
        policy=RecoveryPolicy(
            policy_id="recovery-policy-retry-enabled",
            allow_retry_request=True,
        ),
    )

    assert outcome.verification.disposition is PostDeliveryVerificationDisposition.TIMED_OUT
    assert outcome.reconciliation_disposition is ExecutionReconciliationDisposition.RETRY_RECOMMENDED
    assert outcome.directive.disposition is RecoveryDirectiveDisposition.QUEUE_RETRY_REQUEST


def test_retry_recommendation_blocked_by_policy_escalates_to_operator() -> None:
    outcome = _run_scenario(
        verification_time=NOW + timedelta(seconds=15),
        retry_allowed=True,
    )

    assert outcome.reconciliation_disposition is ExecutionReconciliationDisposition.RETRY_RECOMMENDED
    assert outcome.directive.disposition is RecoveryDirectiveDisposition.REQUEST_OPERATOR_INTERVENTION
    assert outcome.directive.reason == "retry_request_blocked_by_policy"


def test_persistent_mismatch_requires_operator_intervention() -> None:
    outcome = _run_scenario(
        states=(_state("1800"),),
        mismatch_persistent=True,
    )

    assert outcome.verification.disposition is PostDeliveryVerificationDisposition.MISMATCHED
    assert (
        outcome.reconciliation_disposition
        is ExecutionReconciliationDisposition.OPERATOR_INTERVENTION_REQUIRED
    )
    assert outcome.directive.disposition is RecoveryDirectiveDisposition.REQUEST_OPERATOR_INTERVENTION


def test_changed_assumptions_override_retry_and_request_reevaluation() -> None:
    outcome = _run_scenario(
        verification_time=NOW + timedelta(seconds=15),
        assumptions_current=False,
        retry_allowed=True,
    )

    assert outcome.reconciliation_disposition is ExecutionReconciliationDisposition.REEVALUATE
    assert outcome.directive.disposition is RecoveryDirectiveDisposition.REQUEST_REEVALUATION


def test_failed_delivery_receipt_fails_closed_through_operator_review() -> None:
    outcome = _run_scenario(receipt=_receipt(ExecutionReceiptDisposition.FAILED))

    assert outcome.verification.disposition is PostDeliveryVerificationDisposition.REJECTED
    assert outcome.reconciliation_disposition is ExecutionReconciliationDisposition.ABORT
    assert outcome.directive.disposition is RecoveryDirectiveDisposition.REQUEST_OPERATOR_INTERVENTION


@pytest.mark.parametrize(
    ("step_id", "plan_id", "reason"),
    [
        ("wrong-step", PLAN_ID, "receipt_step_identity_mismatch"),
        (STEP_ID, "wrong-plan", "receipt_plan_identity_mismatch"),
    ],
)
def test_contradictory_receipt_provenance_is_rejected_before_recovery(
    step_id: str,
    plan_id: str,
    reason: str,
) -> None:
    outcome = _run_scenario(receipt=_receipt(step_id=step_id, plan_id=plan_id))

    assert outcome.verification.disposition is PostDeliveryVerificationDisposition.REJECTED
    assert outcome.verification.reason == reason
    assert outcome.reconciliation_disposition is ExecutionReconciliationDisposition.ABORT


def test_identity_and_correlation_provenance_survive_every_boundary() -> None:
    outcome = _run_scenario(states=(_state("2200"),))
    provenance = outcome.directive.provenance

    assert outcome.directive.receipt_id == RECEIPT_ID
    assert outcome.directive.plan_id == PLAN_ID
    assert outcome.directive.step_id == STEP_ID
    assert provenance["source_correlation_id"] == CORRELATION_ID
    assert provenance["source_execution_receipt_id"] == RECEIPT_ID
    assert provenance["source_post_delivery_verification_result_id"] == outcome.verification.result_id
    assert provenance["source_execution_reconciliation_id"] == outcome.directive.reconciliation_id
    assert provenance["source_operational_action_id"] == "action-pump-speed"


def test_exact_replay_is_deterministic_across_all_three_boundaries() -> None:
    first = _run_scenario(states=(_state("2200"),))
    second = _run_scenario(states=(_state("2200"),))

    assert first == second
    assert first.verification.result_id == second.verification.result_id
    assert first.directive.directive_id == second.directive.directive_id


def test_policy_change_changes_directive_identity_without_rewriting_upstream_evidence() -> None:
    blocked = _run_scenario(
        verification_time=NOW + timedelta(seconds=15),
        retry_allowed=True,
    )
    allowed = _run_scenario(
        verification_time=NOW + timedelta(seconds=15),
        retry_allowed=True,
        policy=RecoveryPolicy(
            policy_id="recovery-policy-retry-enabled",
            allow_retry_request=True,
        ),
    )

    assert blocked.verification == allowed.verification
    assert blocked.directive.reconciliation_id == allowed.directive.reconciliation_id
    assert blocked.directive.directive_id != allowed.directive.directive_id


def test_fully_restrictive_policy_fails_closed_without_hidden_action() -> None:
    outcome = _run_scenario(
        verification_time=NOW + timedelta(seconds=15),
        retry_allowed=True,
        policy=RecoveryPolicy(
            policy_id="recovery-policy-deny-all",
            allow_reevaluation_request=False,
            allow_retry_request=False,
            allow_operator_intervention_request=False,
        ),
    )

    assert outcome.directive.disposition is RecoveryDirectiveDisposition.NO_ACTION
    assert not outcome.directive.requires_follow_up
    assert outcome.directive.reason.endswith("operator_request_blocked")
