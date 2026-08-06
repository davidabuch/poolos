from __future__ import annotations

from datetime import datetime, timezone

from poolos.environment import RuntimeMode
from poolos.execution_dispatch_boundary import (
    ExecutionDispatchBoundary,
    ExecutionDispatchBoundaryRequest,
    ExecutionDispatchDisposition,
)
from poolos.execution_models import (
    AuthorizationDisposition,
    ExecutionAuthorization,
    ExecutionProposal,
)
from poolos.execution_plan_authorization import (
    ExecutionPlanAuthorizationDisposition,
    ExecutionPlanAuthorizationRequest,
    ExecutionPlanAuthorizer,
)
from poolos.execution_plan_boundary import ExecutionPlanBoundary
from poolos.execution_plan_constructor import (
    ExecutionPlanConstructionStatus,
    ExecutionPlanConstructor,
)
from poolos.execution_plan_scheduler import (
    ExecutionPlanScheduleDisposition,
    ExecutionPlanScheduleRequest,
    ExecutionPlanScheduler,
)
from poolos.execution_plans import (
    ExecutionPlanBuildRequest,
    ExecutionStepSpecification,
)
from poolos.execution_proposal_boundary import ExecutionProposalBoundary
from poolos.execution_receipt import (
    ExecutionReceiptDisposition,
    InMemoryExecutionReceiptRecorder,
)
from poolos.execution_receipt_builder import ExecutionReceiptBuilder
from poolos.home_assistant_delivery_acknowledgement import (
    HomeAssistantAcknowledgementDisposition,
    HomeAssistantAcknowledgementRequest,
    HomeAssistantDeliveryAcknowledgement,
)
from poolos.home_assistant_transport_adapter import (
    HomeAssistantDeliveryDisposition,
    HomeAssistantServiceCall,
    HomeAssistantTransportAdapter,
)
from poolos.integration import SetPumpSpeed, TranslationResult, VendorCommand
from poolos.operational_action_pipeline import (
    CanonicalOperationalAction,
    OperationalActionPipeline,
)
from poolos.operational_disposition import OperationalDisposition
from poolos.operational_disposition_orchestrator import (
    OperationalAction,
    OperationalTarget,
)
from poolos.transport_delivery_gateway import (
    TransportDeliveryGateway,
    TransportDeliveryGatewayDisposition,
    TransportRoute,
)
from poolos.vendor_translation_boundary import (
    VendorTranslationBoundary,
    VendorTranslationDisposition,
)

NOW = datetime(2026, 8, 6, 4, 0, tzinfo=timezone.utc)
CORRELATION_ID = "correlation-pump-speed-2200"


def _run_vertical_slice():
    action = CanonicalOperationalAction(
        action_id="operational-action-pump-speed-2200",
        action=OperationalAction.REQUEST_PROPOSAL,
        target=OperationalTarget.EXECUTION_PROPOSAL_BOUNDARY,
        context_id="context-pool-filter-cycle",
        disposition=OperationalDisposition.SUBMIT_NEW_PLAN.value,
        reason_code="pump_speed_adjustment_required",
        reason="Set the pool filter pump to 2200 RPM.",
        decision_id="decision-pump-speed-2200",
        correlation_id=CORRELATION_ID,
    )
    pipeline = OperationalActionPipeline().process(action)
    proposal_boundary = ExecutionProposalBoundary().evaluate(pipeline)
    plan_boundary = ExecutionPlanBoundary().evaluate(proposal_boundary)
    assert plan_boundary.plan_request is not None

    operation = SetPumpSpeed(
        equipment_id="pool_filter_pump",
        rpm=2200,
        operation_id="operation-pump-speed-2200",
    )
    proposal = ExecutionProposal(
        proposal_id="proposal-pump-speed-2200",
        decision_id=action.decision_id or "",
        context_id=action.context_id,
        objective_id="objective-filter-circulation",
        created_at=NOW,
        runtime_mode=RuntimeMode.SIMULATION,
        operations=(operation,),
        reason=action.reason,
        expected_final_state={"pool_filter_pump_rpm": 2200},
        metadata={
            "source_proposal_request_id": (
                plan_boundary.plan_request.proposal_request_id
            )
        },
    )
    proposal_authorization = ExecutionAuthorization(
        authorization_id="proposal-authorization-pump-speed-2200",
        proposal_id=proposal.proposal_id,
        evaluated_at=NOW,
        disposition=AuthorizationDisposition.AUTHORIZED,
        reason="Authorized for deterministic vertical-slice construction.",
    )
    build_request = ExecutionPlanBuildRequest(
        proposal=proposal,
        authorization=proposal_authorization,
        step_specifications=(
            ExecutionStepSpecification(
                operation_id=operation.operation_id,
                expected_observations={"pool_filter_pump_rpm": 2200},
            ),
        ),
    )
    construction = ExecutionPlanConstructor().construct(plan_boundary, build_request)
    assert construction.plan is not None

    plan_authorization = ExecutionPlanAuthorizer().authorize(
        ExecutionPlanAuthorizationRequest(
            construction_result=construction,
            evaluated_at=NOW,
            correlation_id=CORRELATION_ID,
        )
    )
    schedule = ExecutionPlanScheduler().schedule(
        ExecutionPlanScheduleRequest(
            authorization_result=plan_authorization,
            evaluated_at=NOW,
            correlation_id=CORRELATION_ID,
        )
    )
    dispatch = ExecutionDispatchBoundary().evaluate(
        ExecutionDispatchBoundaryRequest(
            schedule_result=schedule,
            evaluated_at=NOW,
            correlation_id=CORRELATION_ID,
        )
    )

    def translator(pool_operation) -> TranslationResult:
        assert isinstance(pool_operation, SetPumpSpeed)
        return TranslationResult(
            commands=(
                VendorCommand(
                    vendor="home_assistant",
                    operation="set_value",
                    target="number.pool_filter_pump_rpm",
                    parameters={"value": pool_operation.rpm},
                    metadata={"operation_id": pool_operation.operation_id},
                ),
            ),
            metadata={"translator": "vertical_slice"},
        )

    translation = VendorTranslationBoundary().translate(dispatch, translator)
    gateway = TransportDeliveryGateway().prepare(
        translation,
        lambda command: TransportRoute(
            transport="home_assistant",
            endpoint="number.set_value",
            adapter="home_assistant",
        ),
    )
    assert len(gateway.delivery_requests) == 1

    captured_calls: list[HomeAssistantServiceCall] = []

    def executor(call: HomeAssistantServiceCall):
        captured_calls.append(call)
        return {"status": "success", "context_id": "ha-context-pump-speed-2200"}

    delivery = HomeAssistantTransportAdapter().deliver(
        gateway.delivery_requests[0], executor
    )
    acknowledgement = HomeAssistantDeliveryAcknowledgement().normalize(
        HomeAssistantAcknowledgementRequest(
            delivery_result=delivery,
            observed_at=NOW,
        )
    )
    recorder = InMemoryExecutionReceiptRecorder()
    receipt = ExecutionReceiptBuilder().build(
        acknowledgement,
        recorded_at=NOW,
        recorder=recorder,
    )
    return {
        "action": action,
        "pipeline": pipeline,
        "proposal_boundary": proposal_boundary,
        "plan_boundary": plan_boundary,
        "construction": construction,
        "plan_authorization": plan_authorization,
        "schedule": schedule,
        "dispatch": dispatch,
        "translation": translation,
        "gateway": gateway,
        "delivery": delivery,
        "acknowledgement": acknowledgement,
        "receipt": receipt,
        "recorder": recorder,
        "captured_calls": tuple(captured_calls),
    }


def test_pump_speed_vertical_slice_reaches_recorded_receipt() -> None:
    result = _run_vertical_slice()

    assert result["construction"].status is ExecutionPlanConstructionStatus.CONSTRUCTED
    assert (
        result["plan_authorization"].disposition
        is ExecutionPlanAuthorizationDisposition.AUTHORIZED
    )
    assert result["schedule"].disposition is ExecutionPlanScheduleDisposition.IMMEDIATE
    assert result["dispatch"].disposition is ExecutionDispatchDisposition.READY
    assert result["translation"].disposition is VendorTranslationDisposition.TRANSLATED
    assert (
        result["gateway"].disposition
        is TransportDeliveryGatewayDisposition.PREPARED
    )
    assert result["delivery"].disposition is HomeAssistantDeliveryDisposition.DELIVERED
    assert (
        result["acknowledgement"].disposition
        is HomeAssistantAcknowledgementDisposition.ACKNOWLEDGED
    )
    assert result["receipt"].disposition is ExecutionReceiptDisposition.COMPLETED
    assert result["recorder"].receipts == (result["receipt"],)

    calls = result["captured_calls"]
    assert len(calls) == 1
    assert calls[0].domain == "number"
    assert calls[0].service == "set_value"
    assert calls[0].target == {"entity_id": "number.pool_filter_pump_rpm"}
    assert calls[0].data["value"] == 2200

    receipt = result["receipt"]
    assert receipt.correlation_id == CORRELATION_ID
    assert receipt.provenance["source_execution_plan_id"] == (
        result["construction"].plan.plan_id
    )
    assert receipt.provenance["source_decision_id"] == "decision-pump-speed-2200"
    assert receipt.provenance["source_context_id"] == "context-pool-filter-cycle"
    assert receipt.provenance["source_correlation_id"] == CORRELATION_ID


def test_vertical_slice_replay_preserves_deterministic_identities() -> None:
    first = _run_vertical_slice()
    second = _run_vertical_slice()

    assert first["proposal_boundary"].result_id == second["proposal_boundary"].result_id
    assert first["plan_boundary"].result_id == second["plan_boundary"].result_id
    assert first["construction"].construction_id == second["construction"].construction_id
    assert first["construction"].plan.plan_id == second["construction"].plan.plan_id
    assert (
        first["plan_authorization"].authorization_id
        == second["plan_authorization"].authorization_id
    )
    assert first["schedule"].result_id == second["schedule"].result_id
    assert first["dispatch"].result_id == second["dispatch"].result_id
    assert first["translation"].result_id == second["translation"].result_id
    assert first["gateway"].result_id == second["gateway"].result_id
    assert first["delivery"].result_id == second["delivery"].result_id
    assert (
        first["acknowledgement"].acknowledgement_id
        == second["acknowledgement"].acknowledgement_id
    )
    assert first["receipt"].receipt_id == second["receipt"].receipt_id
