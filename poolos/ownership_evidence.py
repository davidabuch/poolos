"""Platform-neutral ADR-110 evidence and bounded domain reconciliation.

These immutable values belong to the existing lifecycle owners. They cannot
establish provenance, deliver commands, or authorize a physical operation.
Native value changes deliberately carry no operator-origin assertion.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum


class OwnershipDomain(StrEnum):
    BODY = "body"
    PUMP = "pump"
    THERMAL = "thermal"


class OwnershipAuthority(StrEnum):
    NONE = "none"
    POOLOS = "poolos"
    OPERATOR = "operator"
    SAFETY = "safety"


class OwnershipHealth(StrEnum):
    PENDING = "pending"
    CONVERGING = "converging"
    STABLE = "stable"
    RECONCILING = "reconciling"
    FAULTED = "faulted"


class OwnershipEvidenceKind(StrEnum):
    EXPECTED_NATIVE_TRANSITION = "expected_native_transition"
    UNEXPLAINED_DRIFT = "unexplained_drift"
    POSITIVE_OPERATOR_INTERVENTION = "positive_operator_intervention"
    SAFETY_DRIVEN_CHANGE = "safety_driven_change"
    STALE_OR_OLD_GENERATION_CONSEQUENCE = "stale_or_old_generation_consequence"
    COMMAND_OR_CONTROL_FAILURE = "command_or_control_failure"
    LEGITIMATE_LIFECYCLE_TRANSITION = "legitimate_lifecycle_transition"


@dataclass(frozen=True, slots=True)
class PositiveOperatorEvidence:
    """Trusted explicit request, never inferred from its physical consequence.

Adapters must supply the original request identity and originating generation.
An uncorrelated IntelliCenter callback is not a source for this record.
"""

    request_id: str
    authority_generation: int
    body_session_id: str
    domain: OwnershipDomain
    equipment_id: str
    requested_at: datetime

    def __post_init__(self) -> None:
        if not all((self.request_id, self.body_session_id, self.equipment_id)):
            raise ValueError("operator evidence requires request/session/equipment identity")
        if self.authority_generation < 1:
            raise ValueError("operator evidence requires a positive generation")
        _aware(self.requested_at)


    def applies(
        self, *, generation: int, session_id: str, domain: OwnershipDomain,
        equipment_id: str, established_at: datetime, evaluated_at: datetime,
    ) -> bool:
        """Require the exact domain epoch and a non-future original request."""
        _aware(established_at)
        _aware(evaluated_at)
        return (
            self.authority_generation == generation
            and self.body_session_id == session_id
            and self.domain is domain and self.equipment_id == equipment_id
            and established_at <= self.requested_at <= evaluated_at
        )


@dataclass(frozen=True, slots=True)
class ReconciliationEpisode:
    """Fixed budget tied to an existing domain's origin, never evaluation IDs."""

    authority_generation: int
    body_session_id: str
    domain: OwnershipDomain
    equipment_id: str
    policy_identity: str
    origin_id: str
    intended_value: bool | int | str
    started_at: datetime
    deadline: datetime
    correction_budget: int = 2
    correction_request_ids: tuple[str, ...] = ()
    verified_at: datetime | None = None

    def __post_init__(self) -> None:
        _aware(self.started_at)
        _aware(self.deadline)
        if self.deadline <= self.started_at or self.correction_budget < 0:
            raise ValueError("reconciliation requires a finite positive time bound")
        if self.authority_generation < 1 or not all((
            self.body_session_id, self.equipment_id, self.policy_identity, self.origin_id,
        )):
            raise ValueError("reconciliation requires complete origin binding")
        if len(set(self.correction_request_ids)) != len(self.correction_request_ids):
            raise ValueError("duplicate correction request identity")
        if len(self.correction_request_ids) > self.correction_budget:
            raise ValueError("correction budget exhausted")

    def reserve_correction(self, request_id: str, *, at: datetime) -> "ReconciliationEpisode":
        """Reserve before dispatch; retries with the same ID cannot replenish budget."""
        _aware(at)
        if request_id in self.correction_request_ids:
            return self
        if (
            not request_id or at < self.started_at or at >= self.deadline
            or self.verified_at is not None
            or len(self.correction_request_ids) >= self.correction_budget
        ):
            raise ValueError("reconciliation correction not permitted")
        return replace(self, correction_request_ids=(*self.correction_request_ids, request_id))


@dataclass(frozen=True, slots=True)
class DomainOwnershipState:
    """Health and authority augment, and never replace, accepted origin records."""

    domain: OwnershipDomain
    authority: OwnershipAuthority = OwnershipAuthority.NONE
    health: OwnershipHealth = OwnershipHealth.PENDING
    evidence_kind: OwnershipEvidenceKind | None = None
    episode: ReconciliationEpisode | None = None
    positive_operator_evidence: PositiveOperatorEvidence | None = None
    command_blocker: str | None = "ownership_origin_unavailable"
    target_value: bool | int | str | None = None
    observed_value: bool | int | float | str | None = None
    observed_at: datetime | None = None

    def observe(
        self,
        *,
        at: datetime,
        observed_at: datetime | None,
        usable: bool,
        matches: bool,
        expected_transition: bool,
        generation: int,
        session_id: str,
        equipment_id: str,
        policy_identity: str,
        origin_id: str,
        intended_value: bool | int | str,
        operator: PositiveOperatorEvidence | None = None,
        observed_value: bool | int | float | str | None = None,
    ) -> "DomainOwnershipState":
        """Observe existing origin; callers separately enforce exact command gates."""
        _aware(at)
        prior_observed_at = self.observed_at
        prior_observed_value = self.observed_value
        if observed_at is not None:
            _aware(observed_at)
        usable = usable and observed_at is not None and observed_at <= at
        regressive = (observed_at is not None and prior_observed_at is not None
                      and observed_at < prior_observed_at)
        self = replace(self, target_value=intended_value,
                       observed_value=observed_value, observed_at=observed_at)
        if self.authority is not OwnershipAuthority.POOLOS:
            return self  # Equality cannot hand back or adopt authority.
        if operator is not None and (
            operator.authority_generation == generation
            and operator.body_session_id == session_id
            and operator.equipment_id == equipment_id
            and operator.domain is self.domain
            and operator.requested_at <= at
        ):
            return replace(
                self, authority=OwnershipAuthority.OPERATOR,
                evidence_kind=OwnershipEvidenceKind.POSITIVE_OPERATOR_INTERVENTION,
                positive_operator_evidence=operator,
                command_blocker="ownership_operator_domain_override",
            )
        episode = self.episode
        if episode is not None and (
            episode.authority_generation != generation
            or episode.body_session_id != session_id
            or episode.equipment_id != equipment_id
            or episode.policy_identity != policy_identity
            or episode.intended_value != intended_value
        ):
            return replace(self, command_blocker="ownership_reconciliation_binding_changed")
        if self.health is OwnershipHealth.FAULTED:
            return self  # A late match cannot reopen an exhausted episode.
        if episode is not None and episode.verified_at is None and at >= episode.deadline:
            return replace(
                self, health=OwnershipHealth.FAULTED,
                evidence_kind=OwnershipEvidenceKind.COMMAND_OR_CONTROL_FAILURE,
                command_blocker="ownership_reconciliation_deadline_exhausted",
            )
        if regressive:
            # Retain the newest known physical evidence. The old callback may
            # deny permission, but cannot originate a new reconciliation epoch.
            return replace(
                self, observed_at=prior_observed_at, observed_value=prior_observed_value,
                evidence_kind=OwnershipEvidenceKind.STALE_OR_OLD_GENERATION_CONSEQUENCE,
                command_blocker="ownership_evidence_unusable",
            )
        if usable and matches and (
            episode is None
            or (observed_at is not None and observed_at > episode.started_at)
        ):
            return replace(
                self, health=OwnershipHealth.STABLE,
                evidence_kind=OwnershipEvidenceKind.EXPECTED_NATIVE_TRANSITION,
                episode=(None if episode is None else replace(episode, verified_at=observed_at)),
                command_blocker=None,
            )
        # A completed episode remains immutable evidence. A new distinct drift
        # may open a new episode only after a later authoritative observation.
        if episode is not None and episode.verified_at is not None:
            if observed_at is None or observed_at <= episode.verified_at:
                return self
            episode = None
        if episode is None:
            episode = ReconciliationEpisode(
                generation, session_id, self.domain, equipment_id, policy_identity,
                origin_id, intended_value, at, at + timedelta(seconds=120),
            )
        return replace(
            self, episode=episode,
            health=(OwnershipHealth.CONVERGING if expected_transition else OwnershipHealth.RECONCILING),
            evidence_kind=(OwnershipEvidenceKind.EXPECTED_NATIVE_TRANSITION
                           if expected_transition else OwnershipEvidenceKind.UNEXPLAINED_DRIFT),
            command_blocker=("ownership_evidence_unusable" if not usable
                             else "ownership_reconciliation_pending"),
        )

    def permission_denial(self, *, completion_reduction: bool = False) -> str | None:
        """Additional denial, never a command grant or an ownership origin.

        A separately authorized completion reduction may proceed despite a
        control fault; operator and Safety authority still take precedence.
        """
        if self.authority in {OwnershipAuthority.OPERATOR, OwnershipAuthority.SAFETY}:
            return self.authority.value
        if completion_reduction:
            return None
        if self.health is OwnershipHealth.FAULTED:
            return "control_fault"
        if self.command_blocker in {
            "ownership_evidence_unusable", "ownership_reconciliation_binding_changed",
        }:
            return self.command_blocker.removeprefix("ownership_")
        return None

    def diagnostics(self) -> dict[str, object]:
        episode = self.episode
        operator = self.positive_operator_evidence
        return {
            "authority": self.authority.value,
            "health": self.health.value,
            "evidence_classification": None if self.evidence_kind is None else self.evidence_kind.value,
            "command_blocker": self.command_blocker,
            "command_permission": "requires_exact_current_gateway",
            "target": self.target_value,
            "actual": self.observed_value,
            "observed_at": None if self.observed_at is None else self.observed_at.isoformat(),
            "positive_operator_request_id": None if operator is None else operator.request_id,
            "positive_operator_requested_at": None if operator is None else operator.requested_at.isoformat(),
            "reconciliation_origin_id": None if episode is None else episode.origin_id,
            "reconciliation_started_at": None if episode is None else episode.started_at.isoformat(),
            "reconciliation_deadline": None if episode is None else episode.deadline.isoformat(),
            "correction_attempts": 0 if episode is None else len(episode.correction_request_ids),
            "correction_budget": 0 if episode is None else episode.correction_budget,
            "reconciliation_verified_at": None if episode is None or episode.verified_at is None else episode.verified_at.isoformat(),
        }


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("ownership evidence timestamps must be timezone-aware")
