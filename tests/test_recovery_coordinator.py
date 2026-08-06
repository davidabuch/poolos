from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from poolos.execution_reconciliation_planning import (
    ExecutionReconciliationDisposition,
    ExecutionReconciliationResult,
)
from poolos.recovery_coordinator import (
    RecoveryCoordinationRequest,
    RecoveryCoordinator,
    RecoveryDirectiveDisposition,
    RecoveryPolicy,
)

NOW = datetime(2026, 8, 6, 7, 0, tzinfo=timezone.utc)


def _reconciliation(
    disposition: ExecutionReconciliationDisposition,
) -> ExecutionReconciliationResult:
    return ExecutionReconciliationResult(
        reconciliation_id=f"reconciliation-{disposition.value}",
        disposition=disposition,
        evaluated_at=NOW,
        receipt_id="receipt-1",
        verification_result_id="verification-1",
        plan_id="plan-1",
        step_id="step-1",
        reason=f"reason-{disposition.value}",
        provenance={"source_correlation_id": "correlation-1"},
    )


def _request(
    disposition: ExecutionReconciliationDisposition,
    *,
    reevaluation: bool = True,
    retry: bool = False,
    operator: bool = True,
) -> RecoveryCoordinationRequest:
    return RecoveryCoordinationRequest(
        reconciliation_result=_reconciliation(disposition),
        policy=RecoveryPolicy(
            policy_id="policy-safe-default",
            allow_reevaluation_request=reevaluation,
            allow_retry_request=retry,
            allow_operator_intervention_request=operator,
            metadata={"policy_version": "1"},
        ),
        coordinated_at=NOW + timedelta(seconds=1),
        metadata={"runtime": "supervisory"},
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            ExecutionReconciliationDisposition.SATISFIED,
            RecoveryDirectiveDisposition.NO_ACTION,
        ),
        (
            ExecutionReconciliationDisposition.REEVALUATE,
            RecoveryDirectiveDisposition.REQUEST_REEVALUATION,
        ),
        (
            ExecutionReconciliationDisposition.OPERATOR_INTERVENTION_REQUIRED,
            RecoveryDirectiveDisposition.REQUEST_OPERATOR_INTERVENTION,
        ),
        (
            ExecutionReconciliationDisposition.ABORT,
            RecoveryDirectiveDisposition.REQUEST_OPERATOR_INTERVENTION,
        ),
    ],
)
def test_maps_reconciliation_to_policy_authorized_directive(
    source: ExecutionReconciliationDisposition,
    expected: RecoveryDirectiveDisposition,
) -> None:
    result = RecoveryCoordinator().coordinate(_request(source))

    assert result.disposition is expected
    assert result.requires_follow_up is (expected is not RecoveryDirectiveDisposition.NO_ACTION)
    assert result.reconciliation_id == f"reconciliation-{source.value}"
    assert result.provenance["source_correlation_id"] == "correlation-1"
    assert result.provenance["policy_version"] == "1"
    assert result.provenance["runtime"] == "supervisory"


def test_retry_recommendation_requires_explicit_policy_permission() -> None:
    blocked = RecoveryCoordinator().coordinate(
        _request(ExecutionReconciliationDisposition.RETRY_RECOMMENDED)
    )
    allowed = RecoveryCoordinator().coordinate(
        _request(ExecutionReconciliationDisposition.RETRY_RECOMMENDED, retry=True)
    )

    assert blocked.disposition is RecoveryDirectiveDisposition.REQUEST_OPERATOR_INTERVENTION
    assert blocked.reason == "retry_request_blocked_by_policy"
    assert allowed.disposition is RecoveryDirectiveDisposition.QUEUE_RETRY_REQUEST
    assert allowed.reason == "retry_request_authorized_by_policy"


def test_blocked_reevaluation_escalates_to_operator() -> None:
    result = RecoveryCoordinator().coordinate(
        _request(ExecutionReconciliationDisposition.REEVALUATE, reevaluation=False)
    )

    assert result.disposition is RecoveryDirectiveDisposition.REQUEST_OPERATOR_INTERVENTION
    assert result.reason == "reevaluation_blocked_by_policy"


def test_policy_can_fail_closed_to_no_action_when_all_follow_up_is_blocked() -> None:
    result = RecoveryCoordinator().coordinate(
        _request(
            ExecutionReconciliationDisposition.RETRY_RECOMMENDED,
            retry=False,
            operator=False,
        )
    )

    assert result.disposition is RecoveryDirectiveDisposition.NO_ACTION
    assert result.reason.endswith("operator_request_blocked")


def test_deterministic_replay_and_policy_sensitive_identity() -> None:
    coordinator = RecoveryCoordinator()
    request = _request(
        ExecutionReconciliationDisposition.RETRY_RECOMMENDED, retry=True
    )

    first = coordinator.coordinate(request)
    second = coordinator.coordinate(request)
    blocked = coordinator.coordinate(
        _request(ExecutionReconciliationDisposition.RETRY_RECOMMENDED, retry=False)
    )

    assert first == second
    assert first.directive_id == second.directive_id
    assert first.directive_id != blocked.directive_id


def test_request_rejects_naive_or_regressive_time() -> None:
    reconciliation = _reconciliation(ExecutionReconciliationDisposition.SATISFIED)
    policy = RecoveryPolicy(policy_id="policy")

    with pytest.raises(ValueError, match="timezone-aware"):
        RecoveryCoordinationRequest(
            reconciliation_result=reconciliation,
            policy=policy,
            coordinated_at=datetime(2026, 8, 6, 7, 0),
        )
    with pytest.raises(ValueError, match="cannot precede"):
        RecoveryCoordinationRequest(
            reconciliation_result=reconciliation,
            policy=policy,
            coordinated_at=NOW - timedelta(seconds=1),
        )


def test_models_are_immutable_and_validate_identifiers() -> None:
    with pytest.raises(ValueError, match="policy_id"):
        RecoveryPolicy(policy_id="   ")

    policy = RecoveryPolicy(policy_id="policy", metadata={"a": "b"})
    with pytest.raises(TypeError):
        policy.metadata["a"] = "c"  # type: ignore[index]
