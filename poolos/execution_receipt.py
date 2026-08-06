"""Immutable execution receipts and append-only recording contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Protocol


class ExecutionReceiptDisposition(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    UNAVAILABLE = "unavailable"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    receipt_id: str
    disposition: ExecutionReceiptDisposition
    recorded_at: datetime
    acknowledgement_id: str
    delivery_result_id: str
    delivery_request_id: str
    service_call_id: str | None
    correlation_id: str | None
    detail: str | None = None
    raw_acknowledgement: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (
            ("receipt_id", self.receipt_id),
            ("acknowledgement_id", self.acknowledgement_id),
            ("delivery_result_id", self.delivery_result_id),
            ("delivery_request_id", self.delivery_request_id),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be empty")
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")
        if self.service_call_id is not None and not self.service_call_id.strip():
            raise ValueError("service_call_id must not be empty when provided")
        if self.correlation_id is not None and not self.correlation_id.strip():
            raise ValueError("correlation_id must not be empty when provided")
        if self.disposition is not ExecutionReceiptDisposition.COMPLETED and not self.detail:
            raise ValueError("non-completed receipt requires detail")
        object.__setattr__(self, "raw_acknowledgement", MappingProxyType(dict(self.raw_acknowledgement)))
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


class ExecutionReceiptRecorder(Protocol):
    def record(self, receipt: ExecutionReceipt) -> ExecutionReceipt: ...


@dataclass(slots=True)
class InMemoryExecutionReceiptRecorder:
    _receipts: list[ExecutionReceipt] = field(default_factory=list)

    def record(self, receipt: ExecutionReceipt) -> ExecutionReceipt:
        if not isinstance(receipt, ExecutionReceipt):
            raise TypeError("receipt must be an ExecutionReceipt")
        if any(existing.receipt_id == receipt.receipt_id for existing in self._receipts):
            raise ValueError(f"duplicate receipt_id: {receipt.receipt_id}")
        self._receipts.append(receipt)
        return receipt

    @property
    def receipts(self) -> tuple[ExecutionReceipt, ...]:
        return tuple(self._receipts)

    @property
    def latest(self) -> ExecutionReceipt | None:
        return self._receipts[-1] if self._receipts else None
