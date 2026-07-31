"""Human-readable rendering for PoolOS decision explanations."""

from __future__ import annotations

from dataclasses import dataclass

from .decision_intelligence import (
    AlternativeStatus,
    CheckStatus,
    DecisionAlternative,
    DecisionExplanation,
    DecisionOutcome,
)


@dataclass(frozen=True, slots=True)
class HumanReadableExplanation:
    """Immutable human-facing representation of one decision explanation."""

    headline: str
    details: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.headline.strip():
            raise ValueError("headline must not be empty")
        if any(not detail.strip() for detail in self.details):
            raise ValueError("explanation details must not be empty")

    @property
    def text(self) -> str:
        """Return one display-ready plain-text explanation."""

        return " ".join((self.headline, *self.details))


@dataclass(frozen=True, slots=True)
class HumanExplanationRenderer:
    """Render canonical decision intelligence for a non-technical audience."""

    max_alternatives: int = 2
    include_confidence: bool = True

    def __post_init__(self) -> None:
        if self.max_alternatives < 0:
            raise ValueError("max_alternatives must not be negative")

    @staticmethod
    def _score_text(alternative: DecisionAlternative) -> str:
        if alternative.score is None:
            return ""
        return f" ({alternative.score:.0%} fit)"

    @staticmethod
    def _primary_reason(alternative: DecisionAlternative) -> str:
        if not alternative.reasons:
            return ""
        return f" because {alternative.reasons[0].rstrip('.')}"

    def _outcome_detail(self, explanation: DecisionExplanation) -> str:
        selected = explanation.selected_alternative
        if explanation.outcome is DecisionOutcome.SELECTED and selected is not None:
            return (
                f"Selected {selected.label}{self._score_text(selected)}"
                f"{self._primary_reason(selected)}."
            )
        if explanation.outcome is DecisionOutcome.BLOCKED:
            labels = [check.label for check in explanation.blocking_checks]
            if labels:
                return f"Action is blocked by {self._join_labels(labels)}."
            return "Action is currently blocked."
        if explanation.outcome is DecisionOutcome.DEFERRED:
            return "Action is being deferred until conditions change."
        return "No action is needed right now."

    @staticmethod
    def _join_labels(labels: list[str]) -> str:
        if len(labels) == 1:
            return labels[0]
        if len(labels) == 2:
            return f"{labels[0]} and {labels[1]}"
        return f"{', '.join(labels[:-1])}, and {labels[-1]}"

    def _check_detail(self, explanation: DecisionExplanation) -> str | None:
        failed = tuple(
            check
            for check in explanation.checks
            if check.status in {CheckStatus.FAILED, CheckStatus.UNKNOWN}
        )
        if not failed:
            return None
        descriptions = [f"{check.label}: {check.reason.rstrip('.')}" for check in failed]
        return f"Important checks: {'; '.join(descriptions)}."

    def _alternative_detail(self, explanation: DecisionExplanation) -> str | None:
        if self.max_alternatives == 0:
            return None
        alternatives = tuple(
            alternative
            for alternative in explanation.alternatives
            if alternative.status
            in {AlternativeStatus.REJECTED, AlternativeStatus.INFEASIBLE}
        )[: self.max_alternatives]
        if not alternatives:
            return None
        descriptions = []
        for alternative in alternatives:
            disposition = (
                "not available"
                if alternative.status is AlternativeStatus.INFEASIBLE
                else "not selected"
            )
            reason = self._primary_reason(alternative)
            descriptions.append(f"{alternative.label} was {disposition}{reason}")
        return f"Other options: {'; '.join(descriptions)}."

    def _confidence_detail(self, explanation: DecisionExplanation) -> str | None:
        if not self.include_confidence:
            return None
        return f"Decision confidence is {explanation.confidence:.0%}."

    def render(self, explanation: DecisionExplanation) -> HumanReadableExplanation:
        """Render a stable, concise explanation without technical internals."""

        details: list[str] = [self._outcome_detail(explanation)]
        check_detail = self._check_detail(explanation)
        if check_detail is not None:
            details.append(check_detail)
        alternative_detail = self._alternative_detail(explanation)
        if alternative_detail is not None:
            details.append(alternative_detail)
        if explanation.next_change is not None:
            details.append(f"What could change this: {explanation.next_change.rstrip('.')}.")
        confidence_detail = self._confidence_detail(explanation)
        if confidence_detail is not None:
            details.append(confidence_detail)
        return HumanReadableExplanation(
            headline=explanation.summary.rstrip(". ") + ".",
            details=tuple(details),
        )
