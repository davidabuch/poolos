"""Deterministic technical rendering for PoolOS decision explanations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from .decision_intelligence import (
    DecisionAlternative,
    DecisionCheck,
    DecisionEvidence,
    DecisionExplanation,
)


@dataclass(frozen=True, slots=True)
class TechnicalExplanation:
    """Immutable diagnostic representation of one decision explanation."""

    sections: tuple[tuple[str, tuple[str, ...]], ...]

    def __post_init__(self) -> None:
        names = [name for name, _ in self.sections]
        if any(not name.strip() for name in names):
            raise ValueError("section names must not be empty")
        if len(names) != len(set(names)):
            raise ValueError("section names must be unique")
        if any(not line.strip() for _, lines in self.sections for line in lines):
            raise ValueError("technical explanation lines must not be empty")

    @property
    def text(self) -> str:
        """Return a stable display-ready diagnostic document."""

        blocks = []
        for name, lines in self.sections:
            blocks.append("\n".join((f"[{name}]", *lines)))
        return "\n\n".join(blocks)

    def section(self, name: str) -> tuple[str, ...]:
        """Return one named section or an empty tuple when absent."""

        return next((lines for section_name, lines in self.sections if section_name == name), ())


@dataclass(frozen=True, slots=True)
class TechnicalExplanationRenderer:
    """Render the complete canonical decision graph for diagnostics."""

    include_empty_sections: bool = True

    @staticmethod
    def _timestamp(value: datetime | None) -> str:
        if value is None:
            return "none"
        return value.isoformat()

    @staticmethod
    def _metadata_lines(metadata: Mapping[str, str]) -> tuple[str, ...]:
        return tuple(f"{key}={metadata[key]}" for key in sorted(metadata))

    def _evidence_line(self, item: DecisionEvidence) -> str:
        metadata = self._inline_metadata(item.metadata)
        return (
            f"key={item.key} kind={item.kind.value} value={item.value!r} "
            f"source={item.source!r} observed_at={self._timestamp(item.observed_at)}{metadata}"
        )

    @staticmethod
    def _check_line(item: DecisionCheck) -> str:
        evidence = ",".join(item.evidence_keys) if item.evidence_keys else "none"
        return (
            f"id={item.check_id} status={item.status.value} blocking={str(item.blocking).lower()} "
            f"label={item.label!r} reason={item.reason!r} evidence={evidence}"
        )

    def _alternative_line(self, item: DecisionAlternative) -> str:
        score = "none" if item.score is None else f"{item.score:.6f}"
        reasons = " | ".join(item.reasons) if item.reasons else "none"
        metadata = self._inline_metadata(item.metadata)
        return (
            f"rank={item.rank} id={item.alternative_id} status={item.status.value} "
            f"score={score} label={item.label!r} reasons={reasons!r}{metadata}"
        )

    @staticmethod
    def _inline_metadata(metadata: Mapping[str, str]) -> str:
        if not metadata:
            return ""
        values = ",".join(f"{key}={metadata[key]!r}" for key in sorted(metadata))
        return f" metadata={{{values}}}"

    def _section(
        self,
        name: str,
        lines: tuple[str, ...],
    ) -> tuple[str, tuple[str, ...]] | None:
        if lines or self.include_empty_sections:
            return name, lines or ("none",)
        return None

    def render(self, explanation: DecisionExplanation) -> TechnicalExplanation:
        """Render one canonical explanation with stable section and item ordering."""

        selected_id = explanation.selected_alternative_id or "none"
        overview = (
            f"decision_id={explanation.decision_id}",
            f"evaluated_at={explanation.evaluated_at.isoformat()}",
            f"goal={explanation.goal!r}",
            f"outcome={explanation.outcome.value}",
            f"selected_alternative_id={selected_id}",
            f"confidence={explanation.confidence:.6f}",
            f"summary={explanation.summary!r}",
            f"next_change={explanation.next_change!r}",
        )
        candidates = (
            self._section("decision", overview),
            self._section(
                "evidence",
                tuple(self._evidence_line(item) for item in explanation.evidence),
            ),
            self._section("checks", tuple(self._check_line(item) for item in explanation.checks)),
            self._section(
                "alternatives",
                tuple(self._alternative_line(item) for item in explanation.alternatives),
            ),
            self._section("metadata", self._metadata_lines(explanation.metadata)),
        )
        return TechnicalExplanation(tuple(section for section in candidates if section is not None))
