from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from poolos.delivery import (
    PentairCommandClientError,
    PentairCommandRequest,
    PentairCommandTimeoutError,
)
from poolos.homeassistant import (
    HomeAssistantCommandClient,
    HomeAssistantExecutorError,
    HomeAssistantExecutorTimeoutError,
    HomeAssistantServiceCall,
    HomeAssistantServiceResult,
)


@dataclass
class RecordingMapper:
    call: HomeAssistantServiceCall
    requests: list[PentairCommandRequest] = field(default_factory=list)

    def map_command(self, request: PentairCommandRequest) -> HomeAssistantServiceCall:
        self.requests.append(request)
        return self.call


@dataclass
class RecordingExecutor:
    result: HomeAssistantServiceResult
    calls: list[tuple[HomeAssistantServiceCall, float | None]] = field(
        default_factory=list
    )

    def call_service(
        self,
        call: HomeAssistantServiceCall,
        *,
        timeout: float | None = None,
    ) -> HomeAssistantServiceResult:
        self.calls.append((call, timeout))
        return self.result


@dataclass
class ErrorExecutor:
    error: Exception

    def call_service(
        self,
        call: HomeAssistantServiceCall,
        *,
        timeout: float | None = None,
    ) -> HomeAssistantServiceResult:
        raise self.error


def request() -> PentairCommandRequest:
    return PentairCommandRequest(
        operation="pump.set_speed",
        target="filter-pump",
        parameters={"rpm": 2200},
        metadata={"operation_id": "operation-123"},
        correlation_id="correlation-123",
    )


def service_call() -> HomeAssistantServiceCall:
    return HomeAssistantServiceCall(
        domain="number",
        service="set_value",
        target={"entity_id": "number.pool_pump_speed"},
        data={"value": 2200},
        context={"correlation_id": "correlation-123"},
    )


def test_client_maps_and_executes_command() -> None:
    received_at = datetime(2026, 7, 29, tzinfo=timezone.utc)
    mapper = RecordingMapper(service_call())
    executor = RecordingExecutor(
        HomeAssistantServiceResult(
            accepted=True,
            acknowledged=True,
            message="service call completed",
            call_id="ha-call-123",
            received_at=received_at,
            details={"event": "call_service"},
        )
    )
    client = HomeAssistantCommandClient(executor=executor, mapper=mapper)
    command = request()

    response = client.execute(command, timeout=4.5)

    assert mapper.requests == [command]
    assert executor.calls == [(service_call(), 4.5)]
    assert response.accepted
    assert response.acknowledged
    assert response.message == "service call completed"
    assert response.command_id == "ha-call-123"
    assert response.received_at == received_at
    assert response.details["home_assistant"]["domain"] == "number"
    assert response.details["home_assistant"]["service"] == "set_value"
    assert response.details["home_assistant"]["result"] == {
        "event": "call_service"
    }


@pytest.mark.parametrize(
    ("accepted", "acknowledged"),
    [(True, False), (False, False)],
)
def test_client_preserves_executor_outcome(
    accepted: bool,
    acknowledged: bool,
) -> None:
    client = HomeAssistantCommandClient(
        executor=RecordingExecutor(
            HomeAssistantServiceResult(
                accepted=accepted,
                acknowledged=acknowledged,
            )
        ),
        mapper=RecordingMapper(service_call()),
    )

    response = client.execute(request())

    assert response.accepted is accepted
    assert response.acknowledged is acknowledged


@pytest.mark.parametrize(
    ("error", "expected_type"),
    [
        (
            HomeAssistantExecutorTimeoutError("Home Assistant timed out"),
            PentairCommandTimeoutError,
        ),
        (
            HomeAssistantExecutorError("Home Assistant unavailable"),
            PentairCommandClientError,
        ),
    ],
)
def test_client_maps_known_executor_errors(
    error: Exception,
    expected_type: type[Exception],
) -> None:
    client = HomeAssistantCommandClient(
        executor=ErrorExecutor(error),
        mapper=RecordingMapper(service_call()),
    )

    with pytest.raises(expected_type, match=str(error)):
        client.execute(request())


def test_unexpected_executor_error_is_not_hidden() -> None:
    client = HomeAssistantCommandClient(
        executor=ErrorExecutor(RuntimeError("programming error")),
        mapper=RecordingMapper(service_call()),
    )

    with pytest.raises(RuntimeError, match="programming error"):
        client.execute(request())


def test_mapper_error_is_not_hidden() -> None:
    class BrokenMapper:
        def map_command(
            self,
            request: PentairCommandRequest,
        ) -> HomeAssistantServiceCall:
            raise ValueError("entity mapping missing")

    client = HomeAssistantCommandClient(
        executor=RecordingExecutor(HomeAssistantServiceResult(accepted=True)),
        mapper=BrokenMapper(),
    )

    with pytest.raises(ValueError, match="entity mapping missing"):
        client.execute(request())


def test_service_call_normalizes_and_is_immutable() -> None:
    call = HomeAssistantServiceCall(
        domain=" Number ",
        service=" SET_VALUE ",
        target={"entity_id": "number.pool_pump_speed"},
        data={"value": 2200},
        context={"source": "test"},
    )

    assert call.domain == "number"
    assert call.service == "set_value"
    with pytest.raises(TypeError):
        call.data["value"] = 1800  # type: ignore[index]


@pytest.mark.parametrize("field_name", ["domain", "service"])
def test_service_call_requires_identity(field_name: str) -> None:
    values = {"domain": "number", "service": "set_value"}
    values[field_name] = " "

    with pytest.raises(ValueError, match=field_name):
        HomeAssistantServiceCall(**values)


def test_service_result_validates_acknowledgement_and_call_id() -> None:
    with pytest.raises(ValueError, match="cannot be acknowledged"):
        HomeAssistantServiceResult(accepted=False, acknowledged=True)
    with pytest.raises(ValueError, match="call_id"):
        HomeAssistantServiceResult(accepted=True, call_id=" ")


def test_service_result_details_are_immutable() -> None:
    result = HomeAssistantServiceResult(
        accepted=True,
        details={"service_response": {"success": True}},
    )

    with pytest.raises(TypeError):
        result.details["other"] = True  # type: ignore[index]
