from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from poolos.execution_reconciliation_planning import (
    ExecutionReconciliationDisposition,
    ExecutionReconciliationPlanner,
    ExecutionReconciliationRequest,
)
from poolos.post_delivery_observation_verification import (
    PostDeliveryVerificationDisposition,
    PostDeliveryVerificationResult,
)

NOW = datetime(2026, 8, 6, 6, 0, tzinfo=timezone.utc)


def _verification(
    disposition: PostDeliveryVerificationDisposition,
) -> PostDeliveryVerificationResult:
    return PostDeliveryVerificationResult(
        result_id=f"verification-{disposition.value}",
        disposition=disposition,
        evaluated_at=NOW,
        receipt_id="receipt-pump-speed",
        plan_id="plan-pump-speed",
        step_id="step-pump-speed",
        reason=f"reason-{disposition.value}",
        verification=None,
        provenance={"source_correlation_id": "correlation-pump-speed"},
    ) if disposition is PostDeliveryVerificationDisposition.REJECTED else _non_rejected(
        disposition
    )


def _non_rejected(
    disposition: PostDeliveryVerificationDisposition,
) -> PostDeliveryVerificationResult:
    # The planner depends on the canonical boundary result and does not inspect
    # the nested verification payload. A minimal immutable sentinel is safe here.
    from poolos.execution_models import VerificationStatus
    from poolos.execution_verification import (
        ExecutionVerificationEvidence,
        ExecutionVerificationResult,
        VerificationEvidenceDisposition,
    )

    status = {
        PostDeliveryVerificationDisposition.VERIFIED: VerificationStatus.VERIFIED,
        PostDeliveryVerificationDisposition.TIMED_OUT: VerificationStatus.TIMED_OUT,
        PostDeliveryVerificationDisposition.MISMATCHED: VerificationStatus.FAILED,
    }.get(disposition, VerificationStatus.PENDING)
    evidence_disposition = {
        PostDeliveryVerificationDisposition.VERIFIED: VerificationEvidenceDisposition.MATCHED,
        PostDeliveryVerificationDisposition.MISMATCHED: VerificationEvidenceDisposition.MISMATCHED,
        PostDeliveryVerificationDisposition.STALE: VerificationEvidenceDisposition.STALE,
        PostDeliveryVerificationDisposition.UNAVAILABLE: VerificationEvidenceDisposition.UNUSABLE,
    }.get(disposition, VerificationEvidenceDisposition.MISSING)
    nested = ExecutionVerificationResult(
        verification_id=f"nested-{disposition.value}",
        plan_id="plan-pump-speed",
        step_id="step-pump-speed",
        status=status,
        evaluated_at=NOW,
        deadline=NOW + timedelta(seconds=15),
        reason=f"nested-reason-{disposition.value}",
        evidence=(
            ExecutionVerificationEvidence(
                observation_id="pool_filter_pump_rpm",
                expected_value=2200,
                actual_value=(
                    2200
                    if disposition is PostDeliveryVerificationDisposition.VERIFIED
                    else None
                ),
                disposition=evidence_disposition,
                reason=f"evidence-{disposition.value}",
            ),
        ),
    )
    return PostDeliveryVerificationResult(
        result_id=f"verification-{disposition.value}",
        disposition=disposition,
        evaluated_at=NOW,
        receipt_id="receipt-pump-speed",
        plan_id="plan-pump-speed",
        step_id="step-pump-speed",
        reason=f"reason-{disposition.value}",
        verification=nested,
        provenance={"source_correlation_id": "correlation-pump-speed"},
    )


def _request(
    disposition: PostDeliveryVerificationDisposition,
    *,
    assumptions_current: bool = True,
    retry_allowed: bool = False,
    mismatch_persistent: bool = False,
) -> ExecutionReconciliationRequest:
    return ExecutionReconciliationRequest(
        verification_result=_verification(disposition),
        evaluated_at=NOW + timedelta(seconds=1),
        assumptions_current=assumptions_current,
        retry_allowed=retry_allowed,
        mismatch_persistent=mismatch_persistent,
        metadata={"policy_id": "policy-default"},
    )


def test_verified_execution_is_satisfied() -> None:
    result = ExecutionReconciliationPlanner().evaluate(
        _request(PostDeliveryVerificationDisposition.VERIFIED)
    )
    assert result.disposition is ExecutionReconciliationDisposition.SATISFIED
    assert result.reason == "expected_state_verified"
    assert not result.requires_follow_up


def test_rejected_verification_aborts_fail_closed() -> None:
    result = ExecutionReconciliationPlanner().evaluate(
        _request(PostDeliveryVerificationDisposition.REJECTED)
    )
    assert result.disposition is ExecutionReconciliationDisposition.ABORT
    assert result.reason == "verification_evidence_rejected"


def test_changed_assumptions_require_fresh_reevaluation() -> None:
    result = ExecutionReconciliationPlanner().evaluate(
        _request(
            PostDeliveryVerificationDisposition.TIMED_OUT,
            assumptions_current=False,
            retry_allowed=True,
        )
    )
    assert result.disposition is ExecutionReconciliationDisposition.REEVALUATE
    assert result.reason == "execution_assumptions_no_longer_current"


def test_pending_evidence_requests_reevaluation() -> None:
    result = ExecutionReconciliationPlanner().evaluate(
        _request(PostDeliveryVerificationDisposition.PENDING)
    )
    assert result.disposition is ExecutionReconciliationDisposition.REEVALUATE


def test_nonpersistent_mismatch_requests_reevaluation() -> None:
    result = ExecutionReconciliationPlanner().evaluate(
        _request(PostDeliveryVerificationDisposition.MISMATCHED)
    )
    assert result.disposition is ExecutionReconciliationDisposition.REEVALUATE
    assert result.reason == "new_observed_state_requires_reevaluation"


def test_persistent_mismatch_requires_operator() -> None:
    result = ExecutionReconciliationPlanner().evaluate(
        _request(
            PostDeliveryVerificationDisposition.MISMATCHED,
            mismatch_persistent=True,
        )
    )
    assert (
        result.disposition
        is ExecutionReconciliationDisposition.OPERATOR_INTERVENTION_REQUIRED
    )


def test_unavailable_observation_requires_operator() -> None:
    result = ExecutionReconciliationPlanner().evaluate(
        _request(PostDeliveryVerificationDisposition.UNAVAILABLE)
    )
    assert (
        result.disposition
        is ExecutionReconciliationDisposition.OPERATOR_INTERVENTION_REQUIRED
    )


@pytest.mark.parametrize(
    "verification_disposition",
    [
        PostDeliveryVerificationDisposition.STALE,
        PostDeliveryVerificationDisposition.TIMED_OUT,
    ],
)
def test_expired_evidence_recommends_retry_only_when_policy_allows(
    verification_disposition: PostDeliveryVerificationDisposition,
) -> None:
    result = ExecutionReconciliationPlanner().evaluate(
        _request(verification_disposition, retry_allowed=True)
    )
    assert result.disposition is ExecutionReconciliationDisposition.RETRY_RECOMMENDED
    assert result.reason == "verification_evidence_expired_retry_permitted"


def test_expired_evidence_without_retry_permission_requires_operator() -> None:
    result = ExecutionReconciliationPlanner().evaluate(
        _request(PostDeliveryVerificationDisposition.TIMED_OUT)
    )
    assert (
        result.disposition
        is ExecutionReconciliationDisposition.OPERATOR_INTERVENTION_REQUIRED
    )


def test_replay_is_deterministic_and_preserves_provenance() -> None:
    planner = ExecutionReconciliationPlanner()
    request = _request(
        PostDeliveryVerificationDisposition.STALE,
        retry_allowed=True,
    )
    first = planner.evaluate(request)
    second = planner.evaluate(request)

    assert first == second
    assert first.reconciliation_id == second.reconciliation_id
    assert first.provenance["source_execution_receipt_id"] == "receipt-pump-speed"
    assert first.provenance["policy_id"] == "policy-default"


def test_request_rejects_naive_or_backdated_evaluation_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ExecutionReconciliationRequest(
            verification_result=_verification(
                PostDeliveryVerificationDisposition.VERIFIED
            ),
            evaluated_at=datetime(2026, 8, 6, 6, 0),
            assumptions_current=True,
            retry_allowed=False,
        )
    with pytest.raises(ValueError, match="cannot precede"):
        ExecutionReconciliationRequest(
            verification_result=_verification(
                PostDeliveryVerificationDisposition.VERIFIED
            ),
            evaluated_at=NOW - timedelta(seconds=1),
            assumptions_current=True,
            retry_allowed=False,
        )
