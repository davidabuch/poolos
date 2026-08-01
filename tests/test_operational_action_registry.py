from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from poolos.operational_action_pipeline import (
    CanonicalOperationalAction,
    OperationalActionPipeline,
    OperationalActionPipelineReason,
    OperationalActionPipelineStatus,
)
from poolos.operational_action_registry import (
    OperationalActionRegistration,
    OperationalActionRegistry,
    OperationalActionRegistryReason,
    OperationalActionRegistryStatus,
)
from poolos.operational_disposition import (
    OperationalDisposition,
    OperationalEvaluationResult,
    OperationalReasonCode,
)
from poolos.operational_disposition_orchestrator import (
    OperationalAction,
    OperationalDispositionOrchestrator,
    OperationalTarget,
)


def _registration(
    *,
    action: OperationalAction = OperationalAction.REQUEST_PROPOSAL,
    target: OperationalTarget = OperationalTarget.EXECUTION_PROPOSAL_BOUNDARY,
    boundary_name: str = "execution_proposal_boundary",
) -> OperationalActionRegistration:
    return OperationalActionRegistration(
        action=action,
        target=target,
        boundary_name=boundary_name,
        description="Test route",
    )


def _proposal_action() -> CanonicalOperationalAction:
    instruction = OperationalDispositionOrchestrator().orchestrate(
        OperationalEvaluationResult(
            disposition=OperationalDisposition.SUBMIT_NEW_PLAN,
            reason_code=OperationalReasonCode.SELECTED_WITHOUT_PLAN,
            reason="Proposal required",
            context_id="context-1",
            decision_id="decision-1",
        )
    )
    return CanonicalOperationalAction.from_instruction(instruction)


def test_default_registry_contains_every_operational_action() -> None:
    registry = OperationalActionRegistry.default()

    assert {entry.action for entry in registry.registrations} == set(OperationalAction)


@pytest.mark.parametrize(
    ("action", "target"),
    [
        (OperationalAction.NO_ACTION, OperationalTarget.NONE),
        (
            OperationalAction.REQUEST_REEVALUATION,
            OperationalTarget.REEVALUATION_SCHEDULER,
        ),
        (
            OperationalAction.REQUEST_PROPOSAL,
            OperationalTarget.EXECUTION_PROPOSAL_BOUNDARY,
        ),
        (OperationalAction.RETAIN_PLAN, OperationalTarget.EXECUTION_PLAN_BOUNDARY),
        (
            OperationalAction.REQUEST_PLAN_CANCELLATION,
            OperationalTarget.EXECUTION_PLAN_BOUNDARY,
        ),
        (
            OperationalAction.REQUEST_PLAN_REPLACEMENT,
            OperationalTarget.EXECUTION_PLAN_BOUNDARY,
        ),
        (OperationalAction.HALT, OperationalTarget.OPERATOR_REVIEW),
    ],
)
def test_default_registry_resolves_canonical_routes(
    action: OperationalAction,
    target: OperationalTarget,
) -> None:
    result = OperationalActionRegistry.default().lookup(action)

    assert result.status is OperationalActionRegistryStatus.FOUND
    assert result.reason is OperationalActionRegistryReason.ROUTE_FOUND
    assert result.registration is not None
    assert result.registration.target is target


def test_partial_registry_returns_stable_unsupported_result() -> None:
    registry = OperationalActionRegistry(registrations=(_registration(),))

    result = registry.lookup(OperationalAction.HALT)

    assert result.status is OperationalActionRegistryStatus.UNSUPPORTED
    assert result.reason is OperationalActionRegistryReason.UNSUPPORTED_ACTION
    assert result.registration is None
    assert result.diagnostics["operational_action"] == "halt"


def test_registry_rejects_duplicate_registration() -> None:
    registration = _registration()

    with pytest.raises(ValueError, match="duplicate registration"):
        OperationalActionRegistry(registrations=(registration, registration))


def test_registry_rejects_conflicting_registration() -> None:
    with pytest.raises(ValueError, match="conflicting registration"):
        OperationalActionRegistry(
            registrations=(
                _registration(),
                _registration(
                    target=OperationalTarget.OPERATOR_REVIEW,
                    boundary_name="operator_review",
                ),
            )
        )


def test_registration_rejects_actionable_none_target() -> None:
    with pytest.raises(ValueError, match="must identify a target"):
        _registration(target=OperationalTarget.NONE)


def test_registration_rejects_no_action_non_none_target() -> None:
    with pytest.raises(ValueError, match="must target none"):
        _registration(
            action=OperationalAction.NO_ACTION,
            target=OperationalTarget.OPERATOR_REVIEW,
        )


def test_registry_models_and_diagnostics_are_immutable() -> None:
    registry = OperationalActionRegistry.default()
    result = registry.lookup(OperationalAction.REQUEST_PROPOSAL)
    assert result.registration is not None

    with pytest.raises(FrozenInstanceError):
        result.registration.boundary_name = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.diagnostics["registry_status"] = "changed"  # type: ignore[index]


def test_pipeline_uses_registry_as_route_authority() -> None:
    action = _proposal_action()
    pipeline = OperationalActionPipeline(
        registry=OperationalActionRegistry(registrations=(_registration(),))
    )

    result = pipeline.process(action)

    assert result.status is OperationalActionPipelineStatus.ACCEPTED
    assert result.diagnostics["boundary_name"] == "execution_proposal_boundary"


def test_pipeline_rejects_action_missing_from_registry() -> None:
    action = _proposal_action()
    pipeline = OperationalActionPipeline(registry=OperationalActionRegistry(registrations=()))

    result = pipeline.process(action)

    assert result.status is OperationalActionPipelineStatus.REJECTED
    assert result.reason is OperationalActionPipelineReason.UNSUPPORTED_ACTION
    assert result.accepted_action_ids == ()


def test_registry_lookup_is_deterministic() -> None:
    registry = OperationalActionRegistry.default()

    assert registry.lookup(OperationalAction.HALT) == registry.lookup(
        OperationalAction.HALT
    )
