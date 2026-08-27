"""Translate command-free solar eligibility into a canonical PoolOS intent.

This boundary converts a positive SolarEligibilityAssessment into a
MAXIMIZE_SOLAR operational intent.

It performs no Home Assistant I/O, arbitration, pump optimization,
execution planning, command construction, or equipment actuation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from .operational_intent import (
    IntentCriterion,
    OperationalIntent,
    OperationalIntentPriority,
    OperationalIntentSource,
    OperationalIntentType,
)
from .solar_control_policy import SolarEligibilityAssessment


@dataclass(frozen=True, slots=True)
class SolarIntentPolicy:
    """Policy for publishing short-lived solar operational intent."""

    priority: OperationalIntentPriority = OperationalIntentPriority.NORMAL
    expiry: timedelta = timedelta(minutes=2)

    def __post_init__(self) -> None:
        if self.expiry <= timedelta(0):
            raise ValueError("expiry must be positive")


class SolarEligibilityIntentAdapter:
    """Convert eligible solar evidence into declarative operational intent."""

    def __init__(
        self,
        policy: SolarIntentPolicy = SolarIntentPolicy(),
    ) -> None:
        self._policy = policy

    @property
    def policy(self) -> SolarIntentPolicy:
        return self._policy

    def create_intent(
        self,
        assessment: SolarEligibilityAssessment,
    ) -> OperationalIntent | None:
        """Return MAXIMIZE_SOLAR only while the assessment is eligible."""

        if not assessment.eligible:
            return None

        differential = assessment.differential_f
        if differential is None:
            raise ValueError(
                "eligible solar assessment requires differential_f"
            )

        rationale = " ".join(assessment.rationale)

        return OperationalIntent(
            intent_type=OperationalIntentType.MAXIMIZE_SOLAR,
            source=OperationalIntentSource.EQUIPMENT,
            priority=self._policy.priority,
            description=(
                "Use available solar thermal energy for pool heating"
            ),
            requested_at=assessment.evaluated_at,
            source_reference="solar-eligibility-policy",
            preconditions=(
                IntentCriterion(
                    code="solar_thermally_eligible",
                    description=(
                        "Current observations satisfy PoolOS solar "
                        "thermal eligibility policy"
                    ),
                    parameters={
                        "differential_f": differential,
                    },
                ),
            ),
            success_criteria=(
                IntentCriterion(
                    code="solar_heat_no_longer_required",
                    description=(
                        "Solar heating is no longer required when the "
                        "pool target is reached or eligibility is withdrawn"
                    ),
                ),
            ),
            failure_criteria=(
                IntentCriterion(
                    code="solar_eligibility_lost",
                    description=(
                        "Current solar thermal eligibility is no longer "
                        "satisfied"
                    ),
                ),
            ),
            explanation_template=(
                "{description}. Source={source}; priority={priority}."
            ),
            expires_at=assessment.evaluated_at + self._policy.expiry,
            constraints=(
                IntentCriterion(
                    code="command_authority_disabled",
                    description=(
                        "This intent is declarative and grants no command "
                        "or equipment authority"
                    ),
                    parameters={"enabled": True},
                ),
                IntentCriterion(
                    code="solar_assessment_rationale",
                    description="Eligibility rationale retained for audit",
                    parameters={"rationale": rationale},
                ),
            ),
        )
