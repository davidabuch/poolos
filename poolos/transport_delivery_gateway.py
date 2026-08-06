"""Deterministic, non-delivering transport preparation for vendor commands.

Epic 10.16I converts one successful vendor-translation result into immutable,
ordered transport delivery requests. It selects logical transports only and
performs no network operation, Home Assistant call, MQTT publish, HTTP request,
vendor call, acknowledgement, retry, verification, or physical actuation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Callable, Mapping

from .integration import VendorCommand
from .vendor_translation_boundary import (
    VendorTranslatedStep,
    VendorTranslationBoundaryResult,
    VendorTranslationDisposition,
)

TransportResolver = Callable[[VendorCommand], "TransportRoute"]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _derived_id(prefix: str, payload: Mapping[str, object]) -> str:
    canonical = _canonical_json(dict(sorted(payload.items())))
    return prefix + sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _command_payload(command: VendorCommand) -> Mapping[str, object]:
    return {
        "vendor": command.vendor,
        "operation": command.operation,
        "target": command.target,
        "parameters": dict(command.parameters),
        "metadata": dict(command.metadata),
    }


class TransportDeliveryGatewayDisposition(str, Enum):
    """Outcome of one transport-delivery preparation evaluation."""

    PREPARED = "prepared"
    REJECTED = "rejected"


class TransportDeliveryGatewayReason(str, Enum):
    """Stable machine-readable delivery-gateway outcome reasons."""

    DELIVERY_REQUESTS_PREPARED = "delivery_requests_prepared"
    TRANSLATION_NOT_ACCEPTED = "translation_not_accepted"
    TRANSLATION_EVIDENCE_INVALID = "translation_evidence_invalid"
    TRANSPORT_ROUTE_INVALID = "transport_route_invalid"
    TRANSPORT_RESOLUTION_FAILED = "transport_resolution_failed"


@dataclass(frozen=True, slots=True)
class TransportRoute:
    """Logical transport route selected without constructing a live adapter."""

    transport: str
    endpoint: str
    adapter: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("transport", self.transport),
            ("endpoint", self.endpoint),
            ("adapter", self.adapter),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must not be empty")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class TransportDeliveryRequest:
    """Immutable request for a future transport adapter to deliver one command."""

    delivery_request_id: str
    sequence: int
    translation_id: str
    step_id: str
    operation_id: str
    command_index: int
    command: VendorCommand
    route: TransportRoute
    correlation_id: str | None = None
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("delivery_request_id", self.delivery_request_id),
            ("translation_id", self.translation_id),
            ("step_id", self.step_id),
            ("operation_id", self.operation_id),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.sequence < 1:
            raise ValueError("sequence must be at least 1")
        if self.command_index < 1:
            raise ValueError("command_index must be at least 1")
        if not isinstance(self.command, VendorCommand):
            raise TypeError("command must be a VendorCommand")
        if not isinstance(self.route, TransportRoute):
            raise TypeError("route must be a TransportRoute")
        if self.correlation_id is not None and not self.correlation_id.strip():
            raise ValueError("correlation_id must not be empty when provided")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True, slots=True)
class TransportDeliveryGatewayResult:
    """Immutable evidence from one transport-delivery gateway evaluation."""

    result_id: str
    disposition: TransportDeliveryGatewayDisposition
    reason: TransportDeliveryGatewayReason
    translation_result: VendorTranslationBoundaryResult
    delivery_requests: tuple[TransportDeliveryRequest, ...] = ()
    failure_translation_id: str | None = None
    failure_detail: str | None = None
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.result_id.strip():
            raise ValueError("result_id must not be empty")
        requests = tuple(self.delivery_requests)
        if self.disposition is TransportDeliveryGatewayDisposition.PREPARED:
            if self.reason is not TransportDeliveryGatewayReason.DELIVERY_REQUESTS_PREPARED:
                raise ValueError("prepared result requires delivery-requests-prepared reason")
            if not requests:
                raise ValueError("prepared result requires delivery requests")
            expected = list(range(1, len(requests) + 1))
            actual = [request.sequence for request in requests]
            if actual != expected:
                raise ValueError("delivery request sequences must be contiguous and ordered")
            if self.failure_translation_id is not None or self.failure_detail is not None:
                raise ValueError("prepared result cannot contain failure evidence")
        elif requests:
            raise ValueError("rejected result cannot contain delivery requests")
        if self.failure_translation_id is not None and not self.failure_translation_id.strip():
            raise ValueError("failure_translation_id must not be empty when provided")
        if self.failure_detail is not None and not self.failure_detail.strip():
            raise ValueError("failure_detail must not be empty when provided")
        object.__setattr__(self, "delivery_requests", requests)
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True, slots=True)
class TransportDeliveryGateway:
    """Prepare ordered transport requests without invoking any adapter."""

    boundary_name: str = "poolos.transport_delivery_gateway"

    def __post_init__(self) -> None:
        if not self.boundary_name.strip():
            raise ValueError("boundary_name must not be empty")

    def prepare(
        self,
        translation_result: VendorTranslationBoundaryResult,
        resolver: TransportResolver,
    ) -> TransportDeliveryGatewayResult:
        """Route translated commands into immutable non-delivering requests."""

        if translation_result.disposition is not VendorTranslationDisposition.TRANSLATED:
            return self._result(
                translation_result,
                reason=TransportDeliveryGatewayReason.TRANSLATION_NOT_ACCEPTED,
            )
        if not self._valid_translation_evidence(translation_result):
            return self._result(
                translation_result,
                reason=TransportDeliveryGatewayReason.TRANSLATION_EVIDENCE_INVALID,
            )

        correlation_id = translation_result.provenance.get("source_correlation_id") or None
        requests: list[TransportDeliveryRequest] = []
        sequence = 0
        for translated_step in translation_result.translated_steps:
            for command_index, command in enumerate(translated_step.commands, start=1):
                try:
                    route = resolver(command)
                except Exception as exc:
                    return self._result(
                        translation_result,
                        reason=TransportDeliveryGatewayReason.TRANSPORT_RESOLUTION_FAILED,
                        failure_translation_id=translated_step.translation_id,
                        failure_detail=f"{type(exc).__name__}:{exc}",
                    )
                if not isinstance(route, TransportRoute):
                    return self._result(
                        translation_result,
                        reason=TransportDeliveryGatewayReason.TRANSPORT_ROUTE_INVALID,
                        failure_translation_id=translated_step.translation_id,
                        failure_detail="resolver_must_return_transport_route",
                    )

                sequence += 1
                delivery_request_id = _derived_id(
                    "transport-delivery-request-",
                    {
                        "boundary_name": self.boundary_name,
                        "command": _command_payload(command),
                        "command_index": command_index,
                        "route": {
                            "transport": route.transport,
                            "endpoint": route.endpoint,
                            "adapter": route.adapter,
                            "metadata": dict(route.metadata),
                        },
                        "translation_id": translated_step.translation_id,
                        "translation_result_id": translation_result.result_id,
                    },
                )
                requests.append(
                    TransportDeliveryRequest(
                        delivery_request_id=delivery_request_id,
                        sequence=sequence,
                        translation_id=translated_step.translation_id,
                        step_id=translated_step.step_id,
                        operation_id=translated_step.operation_id,
                        command_index=command_index,
                        command=command,
                        route=route,
                        correlation_id=correlation_id,
                        provenance={
                            **dict(translation_result.provenance),
                            **dict(route.metadata),
                            "transport_delivery_gateway": self.boundary_name,
                            "transport_delivery_request_id": delivery_request_id,
                            "source_vendor_translation_result_id": translation_result.result_id,
                            "source_vendor_step_translation_id": translated_step.translation_id,
                            "source_execution_step_id": translated_step.step_id,
                            "source_operation_id": translated_step.operation_id,
                            "source_correlation_id": correlation_id or "",
                            "transport": route.transport,
                            "transport_endpoint": route.endpoint,
                            "transport_adapter": route.adapter,
                        },
                    )
                )

        return self._result(
            translation_result,
            reason=TransportDeliveryGatewayReason.DELIVERY_REQUESTS_PREPARED,
            delivery_requests=tuple(requests),
        )

    @staticmethod
    def _valid_translation_evidence(
        translation_result: VendorTranslationBoundaryResult,
    ) -> bool:
        translated_steps = translation_result.translated_steps
        if not translated_steps:
            return False
        expected_sequences = list(range(1, len(translated_steps) + 1))
        if [step.sequence for step in translated_steps] != expected_sequences:
            return False
        return all(
            isinstance(step, VendorTranslatedStep) and step.commands
            for step in translated_steps
        )

    def _result(
        self,
        translation_result: VendorTranslationBoundaryResult,
        *,
        reason: TransportDeliveryGatewayReason,
        delivery_requests: tuple[TransportDeliveryRequest, ...] = (),
        failure_translation_id: str | None = None,
        failure_detail: str | None = None,
    ) -> TransportDeliveryGatewayResult:
        disposition = (
            TransportDeliveryGatewayDisposition.PREPARED
            if reason is TransportDeliveryGatewayReason.DELIVERY_REQUESTS_PREPARED
            else TransportDeliveryGatewayDisposition.REJECTED
        )
        result_id = _derived_id(
            "transport-delivery-gateway-result-",
            {
                "boundary_name": self.boundary_name,
                "delivery_request_ids": [
                    request.delivery_request_id for request in delivery_requests
                ],
                "disposition": disposition.value,
                "failure_detail": failure_detail or "",
                "failure_translation_id": failure_translation_id or "",
                "reason": reason.value,
                "translation_result_id": translation_result.result_id,
            },
        )
        provenance = {
            **dict(translation_result.provenance),
            "transport_delivery_gateway": self.boundary_name,
            "transport_delivery_gateway_result_id": result_id,
            "transport_delivery_gateway_disposition": disposition.value,
            "transport_delivery_gateway_reason": reason.value,
            "source_vendor_translation_result_id": translation_result.result_id,
            "delivery_request_count": str(len(delivery_requests)),
            "failure_translation_id": failure_translation_id or "",
            "failure_detail": failure_detail or "",
        }
        return TransportDeliveryGatewayResult(
            result_id=result_id,
            disposition=disposition,
            reason=reason,
            translation_result=translation_result,
            delivery_requests=delivery_requests,
            failure_translation_id=failure_translation_id,
            failure_detail=failure_detail,
            provenance=provenance,
        )
