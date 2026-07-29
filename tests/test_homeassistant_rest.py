from __future__ import annotations

import json
import socket
from dataclasses import dataclass, field
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from poolos.homeassistant import (
    HomeAssistantExecutorError,
    HomeAssistantExecutorTimeoutError,
    HomeAssistantRestServiceExecutor,
    HomeAssistantServiceCall,
)


@dataclass
class FakeResponse:
    body: bytes = b"[]"
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)

    def read(self) -> bytes:
        return self.body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


@dataclass
class RecordingOpener:
    response: FakeResponse | None = None
    error: Exception | None = None
    calls: list[tuple[Request, float | None]] = field(default_factory=list)

    def open(self, request: Request, timeout: float | None = None) -> FakeResponse:
        self.calls.append((request, timeout))
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def service_call() -> HomeAssistantServiceCall:
    return HomeAssistantServiceCall(
        domain="number",
        service="set_value",
        target={"entity_id": "number.pool_pump_speed"},
        data={"value": 2200},
        context={"correlation_id": "correlation-123"},
    )


def test_executor_builds_authenticated_service_request() -> None:
    opener = RecordingOpener(
        response=FakeResponse(
            body=b'{"context":{"id":"ha-context-123"}}',
            headers={"Content-Type": "application/json"},
        )
    )
    executor = HomeAssistantRestServiceExecutor(
        base_url="http://homeassistant.local:8123/",
        access_token="secret-token",
        timeout=9.0,
        opener=opener,
    )

    result = executor.call_service(service_call(), timeout=4.5)

    request, timeout = opener.calls[0]
    assert request.full_url == (
        "http://homeassistant.local:8123/api/services/number/set_value"
    )
    assert request.method == "POST"
    assert request.get_header("Authorization") == "Bearer secret-token"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data or b"") == {
        "entity_id": "number.pool_pump_speed",
        "value": 2200,
    }
    assert timeout == 4.5
    assert result.accepted
    assert result.acknowledged
    assert result.call_id == "ha-context-123"
    assert result.details["http_status"] == 200
    assert result.details["context"] == {"correlation_id": "correlation-123"}


def test_executor_uses_default_timeout_and_header_call_id() -> None:
    opener = RecordingOpener(
        response=FakeResponse(body=b"", headers={"X-Request-ID": "request-123"})
    )
    executor = HomeAssistantRestServiceExecutor(
        "https://ha.example.test",
        "token",
        timeout=7.0,
        opener=opener,
    )

    result = executor.call_service(service_call())

    assert opener.calls[0][1] == 7.0
    assert result.call_id == "request-123"
    assert result.details["response"] is None


@pytest.mark.parametrize("status", [200, 201, 202])
def test_executor_accepts_success_statuses(status: int) -> None:
    executor = HomeAssistantRestServiceExecutor(
        "https://ha.example.test",
        "token",
        opener=RecordingOpener(response=FakeResponse(status=status)),
    )

    result = executor.call_service(service_call())

    assert result.accepted
    assert str(status) in result.message


def test_executor_rejects_duplicate_target_and_data_keys() -> None:
    executor = HomeAssistantRestServiceExecutor(
        "https://ha.example.test",
        "token",
        opener=RecordingOpener(response=FakeResponse()),
    )
    call = HomeAssistantServiceCall(
        domain="switch",
        service="turn_on",
        target={"entity_id": "switch.pool"},
        data={"entity_id": "switch.other"},
    )

    with pytest.raises(ValueError, match="duplicate keys: entity_id"):
        executor.call_service(call)


@pytest.mark.parametrize(
    "error",
    [TimeoutError("timed out"), socket.timeout("timed out"), URLError(TimeoutError())],
)
def test_executor_maps_timeout_failures(error: Exception) -> None:
    executor = HomeAssistantRestServiceExecutor(
        "https://ha.example.test",
        "token",
        opener=RecordingOpener(error=error),
    )

    with pytest.raises(HomeAssistantExecutorTimeoutError, match="timed out"):
        executor.call_service(service_call())


def test_executor_maps_url_error() -> None:
    executor = HomeAssistantRestServiceExecutor(
        "https://ha.example.test",
        "token",
        opener=RecordingOpener(error=URLError("connection refused")),
    )

    with pytest.raises(HomeAssistantExecutorError, match="connection refused"):
        executor.call_service(service_call())


def test_executor_maps_http_error_with_body() -> None:
    error = HTTPError(
        "https://ha.example.test/api/services/switch/turn_on",
        401,
        "Unauthorized",
        {},
        BytesIO(b'{"message":"Invalid token"}'),
    )
    executor = HomeAssistantRestServiceExecutor(
        "https://ha.example.test",
        "token",
        opener=RecordingOpener(error=error),
    )

    with pytest.raises(HomeAssistantExecutorError, match="HTTP 401"):
        executor.call_service(service_call())


def test_executor_rejects_invalid_json_response() -> None:
    executor = HomeAssistantRestServiceExecutor(
        "https://ha.example.test",
        "token",
        opener=RecordingOpener(response=FakeResponse(body=b"not-json")),
    )

    with pytest.raises(HomeAssistantExecutorError, match="not valid JSON"):
        executor.call_service(service_call())


@pytest.mark.parametrize(
    ("base_url", "token", "timeout", "message"),
    [
        (" ", "token", 1.0, "base_url"),
        ("homeassistant.local", "token", 1.0, "http or https"),
        ("https://ha.example.test", " ", 1.0, "access_token"),
        ("https://ha.example.test", "token", 0.0, "timeout"),
    ],
)
def test_executor_validates_configuration(
    base_url: str,
    token: str,
    timeout: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        HomeAssistantRestServiceExecutor(base_url, token, timeout=timeout)


def test_executor_validates_per_call_timeout() -> None:
    executor = HomeAssistantRestServiceExecutor(
        "https://ha.example.test",
        "token",
        opener=RecordingOpener(response=FakeResponse()),
    )

    with pytest.raises(ValueError, match="timeout"):
        executor.call_service(service_call(), timeout=-1)
