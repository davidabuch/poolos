"""Immutable operator annotation for expected observation outages.

Annotations add retrospective context only. They never alter observation truth,
health state, equipment state, or operational authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from hashlib import sha256
import json
from typing import Any

SCHEMA_VERSION = "1.0.0"


class ExpectedOutageClassification(str, Enum):
    """Stable classification added to a matched observation incident."""

    EXPECTED_OUTAGE = "EXPECTED_OUTAGE"


class ExpectedOutageSource(str, Enum):
    """Authority that supplied expected-outage context."""

    OPERATOR_ACKNOWLEDGED = "OPERATOR_ACKNOWLEDGED"


@dataclass(frozen=True, slots=True)
class ExpectedOutageMatchingPolicy:
    """Explicit matching-window policy; not an asserted outage duration."""

    before: timedelta = timedelta(hours=2)
    after: timedelta = timedelta(hours=2)

    def __post_init__(self) -> None:
        if self.before < timedelta(0) or self.after < timedelta(0):
            raise ValueError("expected-outage matching durations must not be negative")


DEFAULT_EXPECTED_OUTAGE_MATCHING_POLICY = ExpectedOutageMatchingPolicy()


@dataclass(frozen=True, slots=True)
class ExpectedOutageAcknowledgment:
    """Durable operator evidence used to classify intersecting incidents."""

    acknowledgment_id: str
    schema_version: str
    acknowledged_at: datetime
    matching_window_start: datetime
    matching_window_end: datetime
    classification: ExpectedOutageClassification
    source: ExpectedOutageSource
    source_id: str
    reason_code: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("acknowledged_at", self.acknowledged_at),
            ("matching_window_start", self.matching_window_start),
            ("matching_window_end", self.matching_window_end),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.matching_window_end < self.matching_window_start:
            raise ValueError("matching window end must not precede its start")
        if not self.acknowledgment_id.strip() or not self.source_id.strip():
            raise ValueError("acknowledgment and source identities must not be blank")

    @classmethod
    def create(
        cls,
        *,
        acknowledged_at: datetime,
        source_id: str,
        policy: ExpectedOutageMatchingPolicy = DEFAULT_EXPECTED_OUTAGE_MATCHING_POLICY,
        reason_code: str | None = None,
    ) -> ExpectedOutageAcknowledgment:
        """Construct deterministic acknowledgment evidence from explicit inputs."""

        if acknowledged_at.tzinfo is None or acknowledged_at.utcoffset() is None:
            raise ValueError("acknowledged_at must be timezone-aware")
        if not source_id.strip():
            raise ValueError("source_id must not be blank")
        acknowledged_at = acknowledged_at.astimezone(UTC)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "acknowledged_at": acknowledged_at.isoformat(),
            "matching_window_start": (acknowledged_at - policy.before).isoformat(),
            "matching_window_end": (acknowledged_at + policy.after).isoformat(),
            "classification": ExpectedOutageClassification.EXPECTED_OUTAGE.value,
            "source": ExpectedOutageSource.OPERATOR_ACKNOWLEDGED.value,
            "source_id": source_id,
            "reason_code": reason_code,
        }
        acknowledgment_id = "expected-outage-ack-" + sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest()[:24]
        return cls(
            acknowledgment_id=acknowledgment_id,
            schema_version=SCHEMA_VERSION,
            acknowledged_at=acknowledged_at,
            matching_window_start=acknowledged_at - policy.before,
            matching_window_end=acknowledged_at + policy.after,
            classification=ExpectedOutageClassification.EXPECTED_OUTAGE,
            source=ExpectedOutageSource.OPERATOR_ACKNOWLEDGED,
            source_id=source_id,
            reason_code=reason_code,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "acknowledgment_id": self.acknowledgment_id,
            "schema_version": self.schema_version,
            "acknowledged_at": self.acknowledged_at.isoformat(),
            "matching_window_start": self.matching_window_start.isoformat(),
            "matching_window_end": self.matching_window_end.isoformat(),
            "classification": self.classification.value,
            "source": self.source.value,
            "source_id": self.source_id,
            "reason_code": self.reason_code,
            "authority": "none",
            "annotation_authority": "operator_context_only",
            "command_delivery_enabled": False,
        }


def intervals_intersect(
    left_start: datetime,
    left_end: datetime,
    right_start: datetime,
    right_end: datetime,
) -> bool:
    """Return inclusive interval overlap, including exact boundary contact."""

    return left_start <= right_end and right_start <= left_end


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


__all__ = [
    "DEFAULT_EXPECTED_OUTAGE_MATCHING_POLICY",
    "ExpectedOutageAcknowledgment",
    "ExpectedOutageClassification",
    "ExpectedOutageMatchingPolicy",
    "ExpectedOutageSource",
    "SCHEMA_VERSION",
    "intervals_intersect",
]
