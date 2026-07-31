"""Append-only persistence models for PoolOS decision intelligence."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Protocol

from .decision_intelligence import DecisionExplanation
from .human_explanation import HumanReadableExplanation
from .technical_explanation import TechnicalExplanation


class DecisionRecorder(Protocol):
    """Contract used by explainable planning to persist decision records."""

    def record(
        self,
        *,
        plan_id: str,
        objective_id: str,
        decision: DecisionExplanation,
        human: HumanReadableExplanation,
        technical: TechnicalExplanation,
        recorded_at: datetime,
    ) -> "DecisionFlightRecord":
        ...


@dataclass(frozen=True, slots=True)
class DecisionFlightRecord:
    """One immutable append-only decision record."""

    sequence: int
    recorded_at: datetime
    plan_id: str
    objective_id: str
    decision: DecisionExplanation
    human_text: str
    technical_text: str

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("record sequence must be at least 1")
        if self.recorded_at.tzinfo is None:
            raise ValueError("recorded_at must be timezone-aware")
        if not self.plan_id.strip() or not self.objective_id.strip():
            raise ValueError("plan_id and objective_id must not be empty")
        if not self.human_text.strip() or not self.technical_text.strip():
            raise ValueError("rendered explanations must not be empty")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible deterministic record payload."""

        return {
            "sequence": self.sequence,
            "recorded_at": self.recorded_at.isoformat(),
            "plan_id": self.plan_id,
            "objective_id": self.objective_id,
            "decision_id": self.decision.decision_id,
            "outcome": self.decision.outcome.value,
            "selected_alternative_id": self.decision.selected_alternative_id,
            "confidence": self.decision.confidence,
            "human_text": self.human_text,
            "technical_text": self.technical_text,
        }


@dataclass(slots=True)
class InMemoryDecisionFlightRecorder:
    """Deterministic in-memory append-only recorder for decisions."""

    _records: list[DecisionFlightRecord] = field(default_factory=list)

    def record(
        self,
        *,
        plan_id: str,
        objective_id: str,
        decision: DecisionExplanation,
        human: HumanReadableExplanation,
        technical: TechnicalExplanation,
        recorded_at: datetime,
    ) -> DecisionFlightRecord:
        """Append one record and assign the next stable sequence number."""

        record = DecisionFlightRecord(
            sequence=len(self._records) + 1,
            recorded_at=recorded_at,
            plan_id=plan_id,
            objective_id=objective_id,
            decision=decision,
            human_text=human.text,
            technical_text=technical.text,
        )
        self._records.append(record)
        return record

    @property
    def records(self) -> tuple[DecisionFlightRecord, ...]:
        """Return all records in append order."""

        return tuple(self._records)

    @property
    def latest(self) -> Optional[DecisionFlightRecord]:
        """Return the most recently appended record, if present."""

        return self._records[-1] if self._records else None

    def history_for_plan(self, plan_id: str) -> tuple[DecisionFlightRecord, ...]:
        """Return records associated with one plan."""

        return tuple(record for record in self._records if record.plan_id == plan_id)

    def history_for_objective(self, objective_id: str) -> tuple[DecisionFlightRecord, ...]:
        """Return records associated with one objective across plan revisions."""

        return tuple(
            record for record in self._records if record.objective_id == objective_id
        )

    def export_json(self) -> str:
        """Export records as stable compact JSON for snapshots or persistence."""

        return json.dumps(
            [record.to_dict() for record in self._records],
            sort_keys=True,
            separators=(",", ":"),
        )
