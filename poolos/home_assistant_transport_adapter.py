"""Home Assistant transport adapter with injected, testable service execution.

Epic 10.17A converts one prepared Home Assistant transport-delivery request
into an immutable Home Assistant service call and optionally invokes a
caller-supplied executor. The adapter contains no PoolOS business policy,
authentication, retry, backoff, state reconciliation, or direct network code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .transport_delivery_gateway import TransportDeliveryRequest

HomeAssistantServiceExecutor = Callable[["HomeAssistantServiceCall"], Mapping[str, Any] | None]


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


class HomeAssistantDeliveryDisposition(str, Enum):
    """Outcome of one Home Assistant transport-adapter invocation."""

    DELIVERED = "delivered"
    FAILED = "failed"
    REJECTED = "rejected"


class HomeAssistantDeliveryReason(str, Enum):
    """Stable machine-readable adapter outcome reasons."""

    SERVICE_CALL_DELIVERED = "service_call_delivered"
    DELIVERY_REQUEST_INVALID = "delivery_request_invalid"
    TRANSPORT_NOT_SUPPORTED = "transport_not_supported"
    ADAPTER_NOT_SUPPORTED = "adapter_not_supported"
    ENDPOINT_INVALID = "endpoint_invalid"
    EXECUTOR_FAILED = "executor_failed"
    EXECUTOR_RESULT_INVALID = "executor_result_invalid"


@dataclass(frozen=True, slots=True)
class HomeAssistantServiceCall:
    """Immutable Home Assistant service-call request."""

    service_call_id: str
    domain: str
    service: str
    target: Mapping[str, Any]
    data: Mapping[str, Any]
    delivery_request_id: str
    correlation_id: str | None = None
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("service_call_id", self.service_call_id),
            ("domain", self.domain),
            ("service", self.service),
            ("delivery_request_id", self.delivery_request_id),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.correlation_id is not None and not self.correlation_id.strip():
            raise ValueError("correlation_id must not be empty when provided")
        object.__setattr__(self, "target", MappingProxyType(dict(self.target)))
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True, slots=True)
class HomeAssistantDeliveryResult:
    """Immutable evidence from one Home Assistant adapter invocation."""

    result_id: str
    disposition: HomeAssistantDeliveryDisposition
    reason: HomeAssistantDeliveryReason
    delivery_request: TransportDeliveryRequest
    service_call: HomeAssistantServiceCall | None
    acknowledgement: Mapping[str, Any] = field(default_factory=dict)
    failure_detail: str | None = None
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.result_id.strip():
            raise ValueError("result_id must not be empty")
        if self.disposition is HomeAssistantDeliveryDisposition.DELIVERED:
            if self.reason is not HomeAssistantDeliveryReason.SERVICE_CALL_DELIVERED:
                raise ValueError("delivered result requires service-call-delivered reason")
            if self.service_call is None:
                raise ValueError("delivered result requires a service call")
            if self.failure_detail is not None:
                raise ValueError("delivered result cannot contain failure detail")
        elif self.failure_detail is None:
            raise ValueError("failed or rejected result requires failure detail")
        if self.failure_detail is not None and not self.failure_detail.strip():
            raise ValueError("failure_detail must not be empty when provided")
        object.__setattr__(
            self, "acknowledgement", MappingProxyType(dict(self.acknowledgement))
        )
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


@dataclass(frozen=True, slots=True)
class HomeAssistantTransportAdapter:
    """Build and execute Home Assistant service calls through dependency injection."""

    transport_name: str = "home_assistant"
    adapter_name: str = "home_assistant"
    boundary_name: str = "poolos.home_assistant_transport_adapter"

    def __post_init__(self) -> None:
        for field_name, value in (
            ("transport_name", self.transport_name),
            ("adapter_name", self.adapter_name),
            ("boundary_name", self.boundary_name),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must not be empty")

    def deliver(
        self,
        request: TransportDeliveryRequest,
        executor: HomeAssistantServiceExecutor,
    ) -> HomeAssistantDeliveryResult:
        """Build and invoke one Home Assistant service call through ``executor``."""

        rejection = self._validate_request(request)
        if rejection is not None:
            reason, detail = rejection
            return self._result(request, reason=reason, failure_detail=detail)

        service_call = self._build_service_call(request)
        try:
            acknowledgement = executor(service_call)
        except Exception as exc:
            return self._result(
                request,
                reason=HomeAssistantDeliveryReason.EXECUTOR_FAILED,
                service_call=service_call,
                failure_detail=f"{type(exc).__name__}:{exc}",
            )
        if acknowledgement is not None and not isinstance(acknowledgement, Mapping):
            return self._result(
                request,
                reason=HomeAssistantDeliveryReason.EXECUTOR_RESULT_INVALID,
                service_call=service_call,
                failure_detail="executor_must_return_mapping_or_none",
            )

        return self._result(
            request,
            reason=HomeAssistantDeliveryReason.SERVICE_CALL_DELIVERED,
            service_call=service_call,
            acknowledgement={} if acknowledgement is None else dict(acknowledgement),
        )

    def _validate_request(
        self,
        request: TransportDeliveryRequest,
    ) -> tuple[HomeAssistantDeliveryReason, str] | None:
        if not isinstance(request, TransportDeliveryRequest):
            return (
                HomeAssistantDeliveryReason.DELIVERY_REQUEST_INVALID,
                "request_must_be_transport_delivery_request",
            )
        if request.route.transport != self.transport_name:
            return (
                HomeAssistantDeliveryReason.TRANSPORT_NOT_SUPPORTED,
                f"unsupported_transport:{request.route.transport}",
            )
        if request.route.adapter != self.adapter_name:
            return (
                HomeAssistantDeliveryReason.ADAPTER_NOT_SUPPORTED,
                f"unsupported_adapter:{request.route.adapter}",
            )
        endpoint_parts = request.route.endpoint.split(".")
        if len(endpoint_parts) != 2 or any(not part.strip() for part in endpoint_parts):
            return (
                HomeAssistantDeliveryReason.ENDPOINT_INVALID,
                "endpoint_must_be_domain_dot_service",
            )
        return None

    def _build_service_call(
        self,
        request: TransportDeliveryRequest,
    ) -> HomeAssistantServiceCall:
        domain, service = request.route.endpoint.split(".", maxsplit=1)
        command = request.command
        target = {"entity_id": command.target}
        data = {
            **dict(command.parameters),
            "poolos_vendor": command.vendor,
            "poolos_operation": command.operation,
            "poolos_delivery_request_id": request.delivery_request_id,
        }
        service_call_id = _derived_id(
            "home-assistant-service-call-",
            {
                "adapter_name": self.adapter_name,
                "boundary_name": self.boundary_name,
                "data": data,
                "delivery_request_id": request.delivery_request_id,
                "domain": domain,
                "service": service,
                "target": target,
            },
        )
        return HomeAssistantServiceCall(
            service_call_id=service_call_id,
            domain=domain,
            service=service,
            target=target,
            data=data,
            delivery_request_id=request.delivery_request_id,
            correlation_id=request.correlation_id,
            provenance={
                **dict(request.provenance),
                "home_assistant_transport_adapter": self.boundary_name,
                "home_assistant_service_call_id": service_call_id,
                "home_assistant_domain": domain,
                "home_assistant_service": service,
                "source_transport_delivery_request_id": request.delivery_request_id,
                "source_vendor_step_translation_id": request.translation_id,
                "source_execution_step_id": request.step_id,
                "source_operation_id": request.operation_id,
                "source_correlation_id": request.correlation_id or "",
            },
        )

    def _result(
        self,
        request: TransportDeliveryRequest,
        *,
        reason: HomeAssistantDeliveryReason,
        service_call: HomeAssistantServiceCall | None = None,
        acknowledgement: Mapping[str, Any] | None = None,
        failure_detail: str | None = None,
    ) -> HomeAssistantDeliveryResult:
        disposition = {
            HomeAssistantDeliveryReason.SERVICE_CALL_DELIVERED: (
                HomeAssistantDeliveryDisposition.DELIVERED
            ),
            HomeAssistantDeliveryReason.EXECUTOR_FAILED: (
                HomeAssistantDeliveryDisposition.FAILED
            ),
            HomeAssistantDeliveryReason.EXECUTOR_RESULT_INVALID: (
                HomeAssistantDeliveryDisposition.FAILED
            ),
        }.get(reason, HomeAssistantDeliveryDisposition.REJECTED)
        result_id = _derived_id(
            "home-assistant-delivery-result-",
            {
                "boundary_name": self.boundary_name,
                "delivery_request_id": request.delivery_request_id,
                "disposition": disposition.value,
                "failure_detail": failure_detail or "",
                "reason": reason.value,
                "service_call_id": (
                    service_call.service_call_id if service_call is not None else "none"
                ),
            },
        )
        provenance = {
            **dict(request.provenance),
            **(dict(service_call.provenance) if service_call is not None else {}),
            "home_assistant_transport_adapter": self.boundary_name,
            "home_assistant_delivery_result_id": result_id,
            "home_assistant_delivery_disposition": disposition.value,
            "home_assistant_delivery_reason": reason.value,
            "home_assistant_service_call_id": (
                service_call.service_call_id if service_call is not None else ""
            ),
            "source_transport_delivery_request_id": request.delivery_request_id,
            "failure_detail": failure_detail or "",
        }
        return HomeAssistantDeliveryResult(
            result_id=result_id,
            disposition=disposition,
            reason=reason,
            delivery_request=request,
            service_call=service_call,
            acknowledgement={} if acknowledgement is None else acknowledgement,
            failure_detail=failure_detail,
            provenance=provenance,
        )
