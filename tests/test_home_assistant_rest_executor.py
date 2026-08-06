from __future__ import annotations

import json
import socket
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from poolos.home_assistant_rest_executor import (
    HomeAssistantRestAuthenticationError,
    HomeAssistantRestAuthorizationError,
    HomeAssistantRestConnectionError,
    HomeAssistantRestExecutor,
    HomeAssistantRestExecutorConfig,
    HomeAssistantRestResponseError,
    HomeAssistantRestServerError,
    HomeAssistantRestServiceError,
    HomeAssistantRestTimeoutError,
)
from poolos.home_assistant_transport_adapter import (
    HomeAssistantDeliveryDisposition,
    HomeAssistantDeliveryReason,
    HomeAssistantServiceCall,
    HomeAssistantTransportAdapter,
)
from poolos.integration import VendorCommand
from poolos.transport_delivery_gateway import TransportDeliveryRequest, TransportRoute


class FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        body: bytes = b"[]",
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status = status
        self._body = body
        self.headers = {} if headers is None else headers

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _call() -> HomeAssistantServiceCall:
    return HomeAssistantServiceCall(
        service_call_id="service-call-a",
        domain="number",
        service="set_value",
        target={"entity_id": "number.pool_pump_speed"},
        data={"value": 2200},
        delivery_request_id="delivery-a",
        correlation_id="correlation-a",
        provenance={"source_execution_plan_id": "plan-a"},
    )


def _request() -> TransportDeliveryRequest:
    return TransportDeliveryRequest(
        delivery_request_id="delivery-a",
        sequence=1,
        translation_id="translation-a",
        step_id="step-a",
        operation_id="operation-a",
        command_index=1,
        command=VendorCommand(
            vendor="pentair",
            operation="set_speed",
            target="number.pool_pump_speed",
            parameters={"value": 2200},
        ),
        route=TransportRoute(
            transport="home_assistant",
            endpoint="number.set_value",
            adapter="home_assistant",
        ),
        correlation_id="correlation-a",
    )


def _executor(sender: Any) -> HomeAssistantRestExecutor:
    return HomeAssistantRestExecutor(
        HomeAssistantRestExecutorConfig(
            base_url="http://homeassistant.local:8123/",
            access_token="secret-token",
            timeout_seconds=7.5,
        ),
        sender=sender,
    )


def test_posts_canonical_service_request_and_returns_acknowledgement() -> None:
    captured: list[tuple[Request, float]] = []

    def sender(request: Request, timeout: float) -> FakeResponse:
        captured.append((request, timeout))
        return FakeResponse(
            body=b'[{"context":{"id":"ha-context-a"}}]',
            headers={"Content-Type": "application/json"},
        )

    result = _executor(sender)(_call())

    assert len(captured) == 1
    request, timeout = captured[0]
    assert request.full_url == (
        "http://homeassistant.local:8123/api/services/number/set_value"
    )
    assert request.method == "POST"
    assert timeout == 7.5
    assert request.get_header("Authorization") == "Bearer secret-token"
    assert json.loads(request.data or b"") == {
        "entity_id": "number.pool_pump_speed",
        "value": 2200,
    }
    assert result["accepted"] is True
    assert result["http_status"] == 200
    assert result["context_id"] == "ha-context-a"
    assert result["service_call_id"] == "service-call-a"


def test_executor_is_compatible_with_transport_adapter() -> None:
    executor = _executor(lambda request, timeout: FakeResponse(body=b"[]"))

    result = HomeAssistantTransportAdapter().deliver(_request(), executor)

    assert result.disposition is HomeAssistantDeliveryDisposition.DELIVERED
    assert result.reason is HomeAssistantDeliveryReason.SERVICE_CALL_DELIVERED
    assert result.acknowledgement["http_status"] == 200


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, HomeAssistantRestAuthenticationError),
        (403, HomeAssistantRestAuthorizationError),
        (400, HomeAssistantRestServiceError),
        (404, HomeAssistantRestServiceError),
        (500, HomeAssistantRestServerError),
    ],
)
def test_http_statuses_are_normalized(status: int, error_type: type[Exception]) -> None:
    executor = _executor(lambda request, timeout: FakeResponse(status=status))

    with pytest.raises(error_type):
        executor(_call())


def test_http_error_is_normalized_without_response_body_or_token() -> None:
    def sender(request: Request, timeout: float) -> FakeResponse:
        raise HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    with pytest.raises(HomeAssistantRestAuthenticationError) as captured:
        _executor(sender)(_call())

    assert "secret-token" not in str(captured.value)


@pytest.mark.parametrize(
    "failure",
    [TimeoutError(), socket.timeout(), URLError(TimeoutError())],
)
def test_timeouts_are_normalized(failure: Exception) -> None:
    def sender(request: Request, timeout: float) -> FakeResponse:
        raise failure

    with pytest.raises(HomeAssistantRestTimeoutError):
        _executor(sender)(_call())


@pytest.mark.parametrize("failure", [URLError("refused"), OSError("refused")])
def test_connection_failures_are_normalized_and_sanitized(failure: Exception) -> None:
    def sender(request: Request, timeout: float) -> FakeResponse:
        raise failure

    with pytest.raises(HomeAssistantRestConnectionError) as captured:
        _executor(sender)(_call())

    assert str(captured.value) == "Home Assistant REST connection failed"
    assert "secret-token" not in str(captured.value)


def test_malformed_json_is_rejected() -> None:
    executor = _executor(lambda request, timeout: FakeResponse(body=b"not-json"))

    with pytest.raises(HomeAssistantRestResponseError, match="not valid JSON"):
        executor(_call())


def test_empty_response_is_valid() -> None:
    result = _executor(lambda request, timeout: FakeResponse(body=b""))(_call())

    assert result["response"] is None
    assert result["context_id"] is None


def test_header_request_id_has_context_priority() -> None:
    result = _executor(
        lambda request, timeout: FakeResponse(
            body=b'{"context":{"id":"body-id"}}',
            headers={"X-Request-ID": "header-id"},
        )
    )(_call())

    assert result["context_id"] == "header-id"


def test_configuration_is_immutable_normalized_and_secret_safe() -> None:
    config = HomeAssistantRestExecutorConfig(
        base_url=" https://ha.example/ ",
        access_token=" secret-token ",
        timeout_seconds=3,
    )

    assert config.base_url == "https://ha.example"
    assert config.access_token == "secret-token"
    assert "secret-token" not in repr(config)
    assert "secret-token" not in repr(HomeAssistantRestExecutor(config))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"base_url": "", "access_token": "token"},
        {"base_url": "ha.local", "access_token": "token"},
        {"base_url": "http://ha.local", "access_token": ""},
        {
            "base_url": "http://ha.local",
            "access_token": "token",
            "timeout_seconds": 0,
        },
    ],
)
def test_invalid_configuration_is_rejected(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        HomeAssistantRestExecutorConfig(**kwargs)
