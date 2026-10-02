"""Temporal admission shared by observation, ownership and command verification.

Publication time is not observation time. These decisions grant no ownership or
command permission; identity, generation, quality and safety remain caller gates.
"""

from datetime import datetime
from enum import Enum
from typing import Protocol


class EvidenceAdmission(str, Enum):
    UNAVAILABLE = "unavailable"
    PRE_BOUNDARY = "pre_boundary"
    AT_BOUNDARY = "at_boundary"
    POST_BOUNDARY = "post_boundary"


def admit_evidence(observed_at: datetime | None, *, boundary: datetime) -> EvidenceAdmission:
    """Require strictly post-boundary evidence for accepted consequences."""
    if observed_at is None:
        return EvidenceAdmission.UNAVAILABLE
    if observed_at < boundary:
        return EvidenceAdmission.PRE_BOUNDARY
    if observed_at == boundary:
        return EvidenceAdmission.AT_BOUNDARY
    return EvidenceAdmission.POST_BOUNDARY


def evidence_precedes_authority(at: datetime, *, boundary: datetime) -> bool:
    """Old evidence cannot mutate a later authority/confirmation boundary."""
    return admit_evidence(at, boundary=boundary) is EvidenceAdmission.PRE_BOUNDARY


class AcceptedReceipt(Protocol):
    @property
    def issued_at(self) -> datetime: ...

    @property
    def acknowledged_at(self) -> datetime | None: ...


def accepted_command_boundary(receipt: AcceptedReceipt, *, authorized_at: datetime) -> datetime:
    """Use the actual receipt boundary, never backdate acceptance to its frame."""
    times = (authorized_at, receipt.issued_at, receipt.acknowledged_at or receipt.issued_at)
    if any(at.tzinfo is None or at.utcoffset() is None for at in times):
        raise ValueError("accepted command boundary must be timezone-aware")
    return max(times)
