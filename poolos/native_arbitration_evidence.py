"""Immutable read provenance, independent of command and ownership provenance."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .evidence_chronology import EvidenceAdmission, admit_evidence


@dataclass(frozen=True, slots=True)
class NativeArbitrationEvidence:
    read_id: int
    discovery_generation: int
    started_at: datetime
    completed_at: datetime | None
    required_fields: tuple[tuple[str, tuple[str, ...]], ...]
    topology_identity: tuple[tuple[str, str, str, str], ...]
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.started_at.utcoffset() is None:
            raise ValueError("read start must be timezone-aware")
        if self.completed_at is not None and (
            self.completed_at.utcoffset() is None or self.completed_at < self.started_at
        ):
            raise ValueError("read completion must not precede start")

    def admits_boundary(self, boundary: datetime, *, generation: int) -> bool:
        """Read admission only; facts, freshness and authority remain required."""
        return bool(
            self.completed_at is not None
            and self.failure_reason is None
            and generation == self.discovery_generation
            and admit_evidence(self.started_at, boundary=boundary)
            is EvidenceAdmission.POST_BOUNDARY
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            "read_id": self.read_id,
            "discovery_generation": self.discovery_generation,
            "started_at": self.started_at.isoformat(),
            "completed_at": None if self.completed_at is None else self.completed_at.isoformat(),
            "failure_reason": self.failure_reason,
            "status": (
                "failed" if self.failure_reason else
                "waiting" if self.completed_at is None else "complete"
            ),
            "required_object_count": len(self.required_fields),
            "topology_object_count": len(self.topology_identity),
            "authority": "none",
        }
