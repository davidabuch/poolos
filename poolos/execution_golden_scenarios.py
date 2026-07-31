"""Permanent golden-scenario catalog for the supervisory execution pipeline.

The catalog names the end-to-end behaviors that must remain stable as PoolOS
moves from immutable execution artifacts toward simulator-backed delivery.
Scenario implementations live in the test suite and use only supervisory
components; no delivery endpoint or hardware integration is involved.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class ExecutionGoldenScenarioId(str, Enum):
    """Stable identifiers for permanent execution-pipeline scenarios."""

    VERIFIED_EXECUTION = "verified_execution"
    VERIFICATION_NOT_REQUIRED = "verification_not_required"
    AUTHORIZATION_REJECTED = "authorization_rejected"
    AUTHORIZATION_DEFERRED = "authorization_deferred"
    VERIFICATION_FAILED = "verification_failed"
    VERIFICATION_TIMED_OUT = "verification_timed_out"
    INTERRUPTED_DURING_EXECUTION = "interrupted_during_execution"
    INTERRUPTED_DURING_VERIFICATION = "interrupted_during_verification"
    COMPLETED_RESTART_RECOVERY = "completed_restart_recovery"
    CORRUPT_HISTORY = "corrupt_history"


@dataclass(frozen=True, slots=True)
class ExecutionGoldenScenarioDefinition:
    """Immutable definition of one permanent execution golden scenario."""

    scenario_id: ExecutionGoldenScenarioId
    description: str
    expected_terminal_fact: str

    def __post_init__(self) -> None:
        if not self.description.strip():
            raise ValueError("description must not be empty")
        if not self.expected_terminal_fact.strip():
            raise ValueError("expected_terminal_fact must not be empty")


EXECUTION_GOLDEN_SCENARIOS: tuple[ExecutionGoldenScenarioDefinition, ...] = (
    ExecutionGoldenScenarioDefinition(
        ExecutionGoldenScenarioId.VERIFIED_EXECUTION,
        "A verified plan reaches a completed recorded outcome.",
        "completed outcome and no restart action required",
    ),
    ExecutionGoldenScenarioDefinition(
        ExecutionGoldenScenarioId.VERIFICATION_NOT_REQUIRED,
        "A step that requires no verification terminates without evidence.",
        "not-required verification",
    ),
    ExecutionGoldenScenarioDefinition(
        ExecutionGoldenScenarioId.AUTHORIZATION_REJECTED,
        "Rejected authorization never produces an executable plan.",
        "authorization rejected",
    ),
    ExecutionGoldenScenarioDefinition(
        ExecutionGoldenScenarioId.AUTHORIZATION_DEFERRED,
        "Deferred authorization requires fresh reevaluation.",
        "authorization deferred",
    ),
    ExecutionGoldenScenarioDefinition(
        ExecutionGoldenScenarioId.VERIFICATION_FAILED,
        "Fresh contradictory evidence fails verification.",
        "verification failed",
    ),
    ExecutionGoldenScenarioDefinition(
        ExecutionGoldenScenarioId.VERIFICATION_TIMED_OUT,
        "Missing evidence at the deadline times out verification.",
        "verification timed out",
    ),
    ExecutionGoldenScenarioDefinition(
        ExecutionGoldenScenarioId.INTERRUPTED_DURING_EXECUTION,
        "Restart during execution is classified without resumption.",
        "reevaluate and never resume",
    ),
    ExecutionGoldenScenarioDefinition(
        ExecutionGoldenScenarioId.INTERRUPTED_DURING_VERIFICATION,
        "Restart during verification is classified without resumption.",
        "reevaluate and never resume",
    ),
    ExecutionGoldenScenarioDefinition(
        ExecutionGoldenScenarioId.COMPLETED_RESTART_RECOVERY,
        "Completed history requires no execution action after restart.",
        "no action required",
    ),
    ExecutionGoldenScenarioDefinition(
        ExecutionGoldenScenarioId.CORRUPT_HISTORY,
        "Invalid execution history is surfaced for operator attention.",
        "record corruption and await operator",
    ),
)

EXECUTION_GOLDEN_SCENARIO_INDEX: Mapping[
    ExecutionGoldenScenarioId, ExecutionGoldenScenarioDefinition
] = MappingProxyType({item.scenario_id: item for item in EXECUTION_GOLDEN_SCENARIOS})


def validate_execution_golden_catalog() -> None:
    """Raise when the permanent scenario catalog is incomplete or duplicated."""

    identifiers = tuple(item.scenario_id for item in EXECUTION_GOLDEN_SCENARIOS)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("execution golden scenario IDs must be unique")
    if set(identifiers) != set(ExecutionGoldenScenarioId):
        raise ValueError("execution golden scenario catalog is incomplete")
