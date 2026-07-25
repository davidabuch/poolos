"""Built-in hardware-independent PoolOS planning strategies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from .capabilities import Capability
from .commands import Command, CommandAction
from .kernel import PoolKernel
from .planning import (
    ConditionKind,
    FailureBehavior,
    ObjectiveType,
    Plan,
    PlanCondition,
    PlanObjective,
    PlanStatus,
    PlanStep,
    Planner,
)


@dataclass(frozen=True, slots=True)
class PrepareBodyByDeadlineStrategy:
    """Plan circulation and heating to reach a target by a deadline."""

    heating_rate_degrees_per_hour: float = 8.0
    command_window: timedelta = timedelta(minutes=5)
    objective_type: ObjectiveType = ObjectiveType.PREPARE_BODY_BY_DEADLINE

    def __post_init__(self) -> None:
        if self.heating_rate_degrees_per_hour <= 0:
            raise ValueError("heating_rate_degrees_per_hour must be positive")
        if self.command_window <= timedelta(0):
            raise ValueError("command_window must be positive")

    def build(
        self,
        objective: PlanObjective,
        kernel: PoolKernel,
        *,
        revision: int,
        supersedes_plan_id: Optional[str] = None,
        replan_reason: Optional[str] = None,
    ) -> Plan:
        body = kernel.bodies.get(objective.body_id)
        body_state = kernel.state.get_body(objective.body_id)
        if body_state is None:
            raise ValueError(f"no runtime state available for body: {objective.body_id}")

        heater = kernel.equipment.primary_for(Capability.HEATING, body=body.body_type)
        circulation = kernel.equipment.primary_for(
            Capability.CIRCULATION, body=body.body_type
        )
        if heater is None:
            raise ValueError(f"no enabled heater available for body: {objective.body_id}")
        if circulation is None:
            raise ValueError(
                f"no enabled circulation equipment available for body: {objective.body_id}"
            )

        now = kernel.clock.now()
        if now.tzinfo is None:
            raise ValueError("kernel clock must return a timezone-aware datetime")

        temperature_delta = max(
            0.0, objective.target_temperature - body_state.temperature.current
        )
        heat_duration = timedelta(
            hours=temperature_delta / self.heating_rate_degrees_per_hour
        )
        calculated_start = objective.deadline - heat_duration
        start_at = max(objective.earliest_start, calculated_start, now)
        stop_at = objective.maintain_until or objective.deadline

        if temperature_delta == 0:
            return Plan(
                objective_id=objective.objective_id,
                created_at=now,
                horizon_start=max(now, objective.earliest_start),
                horizon_end=stop_at,
                status=PlanStatus.COMPLETED,
                steps=(),
                revision=revision,
                supersedes_plan_id=supersedes_plan_id,
                estimated_completion=now,
                assumptions=(
                    "Current normalized temperature is at or above the requested target.",
                ),
                constraints=("No hardware commands are required.",),
                rationale=("The objective is already satisfied.",),
                replan_reason=replan_reason,
            )

        common_metadata = {
            "objective_id": objective.objective_id,
            "body_id": objective.body_id,
            "target_temperature": objective.target_temperature,
            "planner": self.objective_type.value,
            "plan_revision": revision,
        }
        circulation_step = PlanStep(
            sequence=1,
            earliest_eligible=start_at,
            latest_eligible=start_at + self.command_window,
            commands=(
                Command(
                    target=circulation.id,
                    action=CommandAction.START,
                    priority=objective.priority,
                    requested_by=objective.requested_by,
                    correlation_id=objective.correlation_id,
                    metadata=common_metadata,
                    issued_at=now,
                ),
            ),
            preconditions=(
                PlanCondition(
                    ConditionKind.EQUIPMENT_AVAILABLE, circulation.id, True
                ),
            ),
            completion_conditions=(
                PlanCondition(
                    ConditionKind.BODY_CIRCULATION_RUNNING, objective.body_id, True
                ),
            ),
            failure_behavior=FailureBehavior.REQUEST_REPLAN,
            rationale="Establish circulation before requesting heat.",
        )
        heating_step = PlanStep(
            sequence=2,
            earliest_eligible=start_at,
            latest_eligible=start_at + self.command_window,
            dependencies=(circulation_step.step_id,),
            commands=(
                Command(
                    target=heater.id,
                    action=CommandAction.START,
                    value=objective.target_temperature,
                    priority=objective.priority,
                    requested_by=objective.requested_by,
                    correlation_id=objective.correlation_id,
                    metadata=common_metadata,
                    issued_at=now,
                ),
            ),
            preconditions=(
                PlanCondition(ConditionKind.EQUIPMENT_AVAILABLE, heater.id, True),
                PlanCondition(
                    ConditionKind.BODY_TEMPERATURE_BELOW,
                    objective.body_id,
                    objective.target_temperature,
                ),
            ),
            completion_conditions=(
                PlanCondition(
                    ConditionKind.BODY_TEMPERATURE_AT_LEAST,
                    objective.body_id,
                    objective.target_temperature,
                ),
            ),
            failure_behavior=FailureBehavior.REQUEST_REPLAN,
            rationale="Apply heat after circulation is established.",
        )
        stop_heating_step = PlanStep(
            sequence=3,
            earliest_eligible=stop_at,
            latest_eligible=stop_at + self.command_window,
            dependencies=(heating_step.step_id,),
            commands=(
                Command(
                    target=heater.id,
                    action=CommandAction.STOP,
                    priority=objective.priority,
                    requested_by=objective.requested_by,
                    correlation_id=objective.correlation_id,
                    metadata=common_metadata,
                    issued_at=now,
                ),
            ),
            preconditions=(
                PlanCondition(ConditionKind.TIME_REACHED, objective.body_id, stop_at),
            ),
            failure_behavior=FailureBehavior.CONTINUE,
            rationale="End active heating when the requested maintenance window closes.",
        )

        late_start = start_at >= objective.deadline
        constraints = [
            "Commands remain proposals until policy evaluation and execution.",
            "The estimate assumes a constant configured heating rate.",
        ]
        if late_start:
            constraints.append(
                "Current time or earliest-start constraints leave no estimated heating lead time."
            )

        return Plan(
            objective_id=objective.objective_id,
            created_at=now,
            horizon_start=start_at,
            horizon_end=stop_at + self.command_window,
            status=PlanStatus.DRAFT,
            steps=(circulation_step, heating_step, stop_heating_step),
            revision=revision,
            supersedes_plan_id=supersedes_plan_id,
            estimated_completion=objective.deadline,
            assumptions=(
                f"Heating rate is {self.heating_rate_degrees_per_hour:g} degrees per hour.",
                "Registered circulation and heating equipment remain available.",
            ),
            constraints=tuple(constraints),
            rationale=(
                f"Start no earlier than {start_at.isoformat()} to reach "
                f"{objective.target_temperature:g} by {objective.deadline.isoformat()}.",
            ),
            replan_reason=replan_reason,
        )


def build_default_planner(
    *, heating_rate_degrees_per_hour: float = 8.0
) -> Planner:
    """Return a Planner with the built-in deadline strategy registered."""

    planner = Planner()
    planner.register_strategy(
        PrepareBodyByDeadlineStrategy(
            heating_rate_degrees_per_hour=heating_rate_degrees_per_hour
        )
    )
    return planner
