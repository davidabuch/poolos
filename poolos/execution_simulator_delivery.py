"""Execution-step integration with the simulator execution gateway.

This module connects one canonical :class:`ExecutionStep` to the existing
translation and simulator-gateway boundaries.  It records ordered immutable
receipts and advances lifecycle only through delivery states.  Verification,
coordinator advancement, Home Assistant, Pentair hardware, and physical
actuation remain outside this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping

from .delivery import DeliveryError, DeliveryReceipt
from .execution_models import ExecutionLifecycleStatus, ExecutionPlan, ExecutionStep
from .execution_state_machine import (
    ExecutionLifecycle,
    ExecutionStateMachine,
    ExecutionStateTransition,
)
from .hal import CommandStatus
from .integration import IntegrationError, OperationTranslationHandler, TranslationResult, VendorCommand
from .simulator_execution_gateway import SimulatorExecutionGateway


class SimulatorStepDeliveryDisposition(str, Enum):
    """Terminal disposition of one simulator delivery attempt."""

    DELIVERED = "delivered"
    REJECTED = "rejected"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class SimulatorExecutionReceipt:
    """Execution-scoped identity for one underlying delivery receipt."""

    receipt_id: str
    sequence: int
    delivery_receipt: DeliveryReceipt

    def __post_init__(self) -> None:
        receipt_id = self.receipt_id.strip()
        if not receipt_id:
            raise ValueError("receipt_id must not be empty")
        if self.sequence < 1:
            raise ValueError("sequence must be at least 1")
        object.__setattr__(self, "receipt_id", receipt_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class SimulatorStepDeliveryRequest:
    """All facts required to deliver exactly one execution-plan step."""

    plan: ExecutionPlan
    step: ExecutionStep
    lifecycle: ExecutionLifecycle
    occurred_at: datetime
    endpoint_id: str | None = None
    timeout: float | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if self.timeout is not None and self.timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if self.endpoint_id is not None:
            endpoint_id = self.endpoint_id.strip()
            if not endpoint_id:
                raise ValueError("endpoint_id must not be empty")
            object.__setattr__(self, "endpoint_id", endpoint_id)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True, kw_only=True)
class SimulatorStepDeliveryResult:
    """Immutable result of translating and delivering one execution step."""

    attempt_id: str
    plan_id: str
    step_id: str
    disposition: SimulatorStepDeliveryDisposition
    lifecycle: ExecutionLifecycle
    transitions: tuple[ExecutionStateTransition, ...]
    translation: TranslationResult | None = None
    receipts: tuple[SimulatorExecutionReceipt, ...] = ()
    failed_command: VendorCommand | None = None
    unattempted_commands: tuple[VendorCommand, ...] = ()
    failure_reason: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("attempt_id", "plan_id", "step_id"):
            value = getattr(self, name).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)
        transitions = tuple(self.transitions)
        receipts = tuple(self.receipts)
        unattempted = tuple(self.unattempted_commands)
        if [item.sequence for item in receipts] != list(range(1, len(receipts) + 1)):
            raise ValueError("receipt sequences must be contiguous and ordered from 1")
        if self.disposition is SimulatorStepDeliveryDisposition.DELIVERED:
            if self.failure_reason is not None or self.failed_command is not None:
                raise ValueError("delivered result cannot contain failure details")
        elif not self.failure_reason:
            raise ValueError("non-delivered result requires failure_reason")
        object.__setattr__(self, "transitions", transitions)
        object.__setattr__(self, "receipts", receipts)
        object.__setattr__(self, "unattempted_commands", unattempted)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def delivered(self) -> bool:
        return self.disposition is SimulatorStepDeliveryDisposition.DELIVERED


@dataclass(frozen=True, slots=True)
class SimulatorStepDeliveryEngine:
    """Translate and deliver one plan step through a simulator-only gateway."""

    translation_handler: OperationTranslationHandler
    gateway: SimulatorExecutionGateway
    state_machine: ExecutionStateMachine = field(default_factory=ExecutionStateMachine)
    actor: str = "simulator-step-delivery"

    def __post_init__(self) -> None:
        if not self.actor.strip():
            raise ValueError("actor must not be empty")

    def deliver(self, request: SimulatorStepDeliveryRequest) -> SimulatorStepDeliveryResult:
        self._validate_request(request)
        attempt_id = self._attempt_id(request)
        delivering = self.state_machine.transition(
            request.lifecycle,
            to_status=ExecutionLifecycleStatus.DELIVERING,
            occurred_at=request.occurred_at,
            reason="Simulator delivery started for execution step.",
            actor=self.actor,
            metadata={"step_id": request.step.step_id, "attempt_id": attempt_id},
        )
        if not delivering.applied or delivering.transition is None:
            raise ValueError(delivering.rejection_reason or "delivery transition rejected")

        transitions: list[ExecutionStateTransition] = [delivering.transition]
        lifecycle = delivering.lifecycle
        try:
            translation = self.translation_handler(request.step.operation)
        except IntegrationError as error:
            return self._finish_failure(
                request, attempt_id, lifecycle, transitions,
                SimulatorStepDeliveryDisposition.FAILED,
                f"translation_failed:{type(error).__name__}:{error}",
            )

        receipts: list[SimulatorExecutionReceipt] = []
        commands = translation.commands
        for index, command in enumerate(commands, start=1):
            correlation_id = f"{attempt_id}:command:{index}"
            try:
                receipt = self.gateway.deliver(
                    command,
                    correlation_id=correlation_id,
                    endpoint_id=request.endpoint_id,
                    timeout=request.timeout,
                )
            except DeliveryError as error:
                return self._finish_failure(
                    request, attempt_id, lifecycle, transitions,
                    SimulatorStepDeliveryDisposition.FAILED,
                    f"delivery_error:{type(error).__name__}:{error}",
                    translation=translation,
                    receipts=receipts,
                    failed_command=command,
                    unattempted_commands=commands[index:],
                )

            receipts.append(
                SimulatorExecutionReceipt(
                    receipt_id=f"{attempt_id}:receipt:{index}",
                    sequence=index,
                    delivery_receipt=receipt,
                )
            )
            if receipt.status is CommandStatus.TIMED_OUT:
                return self._finish_failure(
                    request, attempt_id, lifecycle, transitions,
                    SimulatorStepDeliveryDisposition.TIMED_OUT,
                    "simulator_command_timed_out",
                    translation=translation,
                    receipts=receipts,
                    unattempted_commands=commands[index:],
                )
            if receipt.status is CommandStatus.FAILED:
                return self._finish_failure(
                    request, attempt_id, lifecycle, transitions,
                    SimulatorStepDeliveryDisposition.FAILED,
                    "simulator_command_failed",
                    translation=translation,
                    receipts=receipts,
                    unattempted_commands=commands[index:],
                )
            if not receipt.accepted:
                return self._finish_failure(
                    request, attempt_id, lifecycle, transitions,
                    SimulatorStepDeliveryDisposition.REJECTED,
                    "simulator_command_rejected",
                    translation=translation,
                    receipts=receipts,
                    unattempted_commands=commands[index:],
                )

        delivered = self.state_machine.transition(
            lifecycle,
            to_status=ExecutionLifecycleStatus.DELIVERED,
            occurred_at=request.occurred_at,
            reason="All translated simulator commands were accepted.",
            actor=self.actor,
            metadata={"step_id": request.step.step_id, "attempt_id": attempt_id},
        )
        if not delivered.applied or delivered.transition is None:
            raise ValueError(delivered.rejection_reason or "delivered transition rejected")
        transitions.append(delivered.transition)
        return SimulatorStepDeliveryResult(
            attempt_id=attempt_id,
            plan_id=request.plan.plan_id,
            step_id=request.step.step_id,
            disposition=SimulatorStepDeliveryDisposition.DELIVERED,
            lifecycle=delivered.lifecycle,
            transitions=tuple(transitions),
            translation=translation,
            receipts=tuple(receipts),
            metadata=request.metadata,
        )

    def _finish_failure(
        self,
        request: SimulatorStepDeliveryRequest,
        attempt_id: str,
        lifecycle: ExecutionLifecycle,
        transitions: list[ExecutionStateTransition],
        disposition: SimulatorStepDeliveryDisposition,
        reason: str,
        *,
        translation: TranslationResult | None = None,
        receipts: list[SimulatorExecutionReceipt] | None = None,
        failed_command: VendorCommand | None = None,
        unattempted_commands: tuple[VendorCommand, ...] = (),
    ) -> SimulatorStepDeliveryResult:
        target = (
            ExecutionLifecycleStatus.TIMED_OUT
            if disposition is SimulatorStepDeliveryDisposition.TIMED_OUT
            else ExecutionLifecycleStatus.FAILED
        )
        finished = self.state_machine.transition(
            lifecycle,
            to_status=target,
            occurred_at=request.occurred_at,
            reason=reason,
            actor=self.actor,
            metadata={"step_id": request.step.step_id, "attempt_id": attempt_id},
        )
        if not finished.applied or finished.transition is None:
            raise ValueError(finished.rejection_reason or "failure transition rejected")
        transitions.append(finished.transition)
        return SimulatorStepDeliveryResult(
            attempt_id=attempt_id,
            plan_id=request.plan.plan_id,
            step_id=request.step.step_id,
            disposition=disposition,
            lifecycle=finished.lifecycle,
            transitions=tuple(transitions),
            translation=translation,
            receipts=tuple(receipts or ()),
            failed_command=failed_command,
            unattempted_commands=unattempted_commands,
            failure_reason=reason,
            metadata=request.metadata,
        )

    @staticmethod
    def _validate_request(request: SimulatorStepDeliveryRequest) -> None:
        if request.lifecycle.plan_id != request.plan.plan_id:
            raise ValueError("lifecycle plan_id must match plan")
        if request.lifecycle.status is not ExecutionLifecycleStatus.EXECUTING:
            raise ValueError("lifecycle must be EXECUTING before delivery")
        if request.occurred_at < request.lifecycle.updated_at:
            raise ValueError("occurred_at cannot precede lifecycle updated_at")
        matching = tuple(step for step in request.plan.steps if step.step_id == request.step.step_id)
        if len(matching) != 1 or matching[0] != request.step:
            raise ValueError("step must be an exact member of plan")

    @staticmethod
    def _attempt_id(request: SimulatorStepDeliveryRequest) -> str:
        payload = {
            "plan_id": request.plan.plan_id,
            "step_id": request.step.step_id,
            "occurred_at": request.occurred_at.isoformat(),
            "endpoint_id": request.endpoint_id,
            "timeout": request.timeout,
            "metadata": dict(request.metadata),
        }
        digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
        return f"simulator-delivery:{request.plan.plan_id}:{request.step.step_id}:{digest}"
