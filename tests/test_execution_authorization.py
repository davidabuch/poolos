from dataclasses import replace
from datetime import timedelta

import pytest

from poolos.clock import FixedClock
from poolos.delivery import SimulatorVendorCommandEndpoint
from poolos.environment import RuntimeMode, build_runtime_environment
from poolos.evaluation_context import EvaluationRuntimeMode
from poolos.execution_authorization import (
    ExecutionAuthorizationEngine,
    ExecutionAuthorizationRequest,
)
from poolos.execution_models import AuthorizationDisposition
from poolos.execution_proposals import (
    ExecutionProposalGenerator,
    ExecutionProposalRequest,
)
from tests.test_execution_proposals import NOW, completed_result, context, operation

AUTHORIZATION_TIME = NOW + timedelta(seconds=30)


def generated():
    orchestration = completed_result()
    generated_result = ExecutionProposalGenerator().generate(
        ExecutionProposalRequest(
            orchestration=orchestration,
            operations=(operation(),),
            expected_final_state={"pump.running": True},
        )
    )
    assert generated_result.proposal is not None
    assert orchestration.active_record is not None
    return orchestration, generated_result.proposal


def environment(mode: RuntimeMode = RuntimeMode.SIMULATION):
    endpoints = ()
    if mode is RuntimeMode.SIMULATION:
        endpoints = (SimulatorVendorCommandEndpoint(endpoint_id="simulator", vendor="pentair"),)
    return build_runtime_environment(
        mode=mode,
        installation_id="buch-pool",
        endpoints=endpoints,
        clock=FixedClock(AUTHORIZATION_TIME),
    )


def request(**changes):
    orchestration, proposal = generated()
    values = {
        "proposal": proposal,
        "active_record": orchestration.active_record,
        "context": context(),
        "environment": environment(),
        "current_context_id": proposal.context_id,
        "context_valid_until": NOW + timedelta(minutes=5),
    }
    values.update(changes)
    return ExecutionAuthorizationRequest(**values)


def engine() -> ExecutionAuthorizationEngine:
    return ExecutionAuthorizationEngine(clock=FixedClock(AUTHORIZATION_TIME))


def test_authorizes_current_recorded_simulation_proposal() -> None:
    result = engine().authorize(request(metadata={"source": "test"}))

    assert result.authorized
    assert result.disposition is AuthorizationDisposition.AUTHORIZED
    assert result.blocking_reasons == ()
    assert result.metadata["simulator_only"] == "true"
    assert result.metadata["source"] == "test"


def test_authorization_is_deterministic_for_same_preflight_snapshot() -> None:
    value = request()
    first = engine().authorize(value)
    second = engine().authorize(value)

    assert first == second
    assert first.authorization_id == second.authorization_id


def test_rejects_missing_or_noncurrent_recorded_decision() -> None:
    missing = engine().authorize(request(active_record=None))
    assert missing.disposition is AuthorizationDisposition.REJECTED
    assert "decision_not_recorded" in missing.blocking_reasons

    orchestration, _ = generated()
    assert orchestration.active_record is not None
    wrong_record = replace(
        orchestration.active_record,
        objective_id="different-objective",
    )
    mismatch = engine().authorize(request(active_record=wrong_record))
    assert mismatch.disposition is AuthorizationDisposition.REJECTED
    assert "objective_mismatch" in mismatch.blocking_reasons


def test_rejects_superseded_decision() -> None:
    value = request()
    result = engine().authorize(
        replace(
            value,
            superseded_decision_ids=frozenset({value.proposal.decision_id}),
        )
    )

    assert result.disposition is AuthorizationDisposition.REJECTED
    assert "decision_superseded" in result.blocking_reasons


def test_defers_noncurrent_or_expired_context() -> None:
    noncurrent = engine().authorize(request(current_context_id="new-context"))
    assert noncurrent.disposition is AuthorizationDisposition.DEFERRED
    assert "context_not_current" in noncurrent.blocking_reasons

    expired = engine().authorize(request(context_valid_until=NOW))
    assert expired.disposition is AuthorizationDisposition.DEFERRED
    assert "context_expired" in expired.blocking_reasons


def test_defers_context_and_safety_blockers() -> None:
    blocked_context = context(blockers=("telemetry stale",))
    result = engine().authorize(
        request(
            context=blocked_context,
            safety_blockers=("freeze protection active",),
        )
    )

    assert result.disposition is AuthorizationDisposition.DEFERRED
    assert "context_blocker:telemetry stale" in result.blocking_reasons
    assert "safety_blocker:freeze protection active" in result.blocking_reasons


def test_rejects_context_identity_mismatch() -> None:
    result = engine().authorize(request(context=context(context_id="wrong-context")))

    assert result.disposition is AuthorizationDisposition.REJECTED
    assert "proposal_context_mismatch" in result.blocking_reasons


def test_rejects_live_runtime_and_physical_delivery_policy() -> None:
    value = request()
    live_proposal = replace(value.proposal, runtime_mode=RuntimeMode.LIVE)
    live_context = replace(
        value.context,
        runtime_mode=EvaluationRuntimeMode.LIVE,
    )
    result = engine().authorize(
        replace(
            value,
            proposal=live_proposal,
            context=live_context,
            environment=environment(RuntimeMode.LIVE),
        )
    )

    assert result.disposition is AuthorizationDisposition.REJECTED
    assert "live_runtime_prohibited" in result.blocking_reasons
    assert "physical_delivery_prohibited" in result.blocking_reasons


def test_defers_shadow_runtime_during_simulator_only_epic() -> None:
    value = request()
    shadow_proposal = replace(value.proposal, runtime_mode=RuntimeMode.SHADOW)
    shadow_context = replace(
        value.context,
        runtime_mode=EvaluationRuntimeMode.SHADOW,
    )
    result = engine().authorize(
        replace(
            value,
            proposal=shadow_proposal,
            context=shadow_context,
            environment=environment(RuntimeMode.SHADOW),
        )
    )

    assert result.disposition is AuthorizationDisposition.DEFERRED
    assert "shadow_runtime_not_executable" in result.blocking_reasons


def test_rejects_runtime_mismatch() -> None:
    value = request()
    result = engine().authorize(
        replace(value, environment=environment(RuntimeMode.SHADOW))
    )

    assert result.disposition is AuthorizationDisposition.REJECTED
    assert "proposal_environment_runtime_mismatch" in result.blocking_reasons


def test_request_validates_temporal_and_blocker_inputs() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        request(context_valid_until=NOW.replace(tzinfo=None))

    with pytest.raises(ValueError, match="safety blockers"):
        request(safety_blockers=("",))


def test_deferred_authorization_requires_blocking_reason() -> None:
    from poolos.execution_models import ExecutionAuthorization

    with pytest.raises(ValueError, match="deferred disposition requires"):
        ExecutionAuthorization(
            authorization_id="authorization",
            proposal_id="proposal",
            evaluated_at=AUTHORIZATION_TIME,
            disposition=AuthorizationDisposition.DEFERRED,
            reason="Deferred.",
        )


def test_authorization_does_not_deliver_to_simulator_endpoint() -> None:
    value = request()
    endpoint = value.environment.endpoints[0]
    before = endpoint.transport.metadata()

    result = engine().authorize(value)

    after = endpoint.transport.metadata()
    assert result.authorized
    assert after == before
