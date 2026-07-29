"""Generic Home Assistant command client built on injected mapping and execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from poolos.delivery.pentair import (
    PentairCommandClientError,
    PentairCommandRequest,
    PentairCommandResponse,
    PentairCommandTimeoutError,
)

from .models import HomeAssistantServiceCall, HomeAssistantServiceResult

RequestT = TypeVar("RequestT", contravariant=True)


class HomeAssistantExecutorError(Exception):
    """Base class for known Home Assistant executor failures."""


class HomeAssistantExecutorTimeoutError(HomeAssistantExecutorError):
    """Raised when a Home Assistant service call exceeds its timeout."""


class HomeAssistantServiceExecutor(Protocol):
    """Port implemented by a concrete Home Assistant REST or WebSocket adapter."""

    def call_service(
        self,
        call: HomeAssistantServiceCall,
        *,
        timeout: float | None = None,
    ) -> HomeAssistantServiceResult: ...


class HomeAssistantCommandMapper(Protocol[RequestT]):
    """Map one provider command request to one Home Assistant service call."""

    def map_command(self, request: RequestT) -> HomeAssistantServiceCall: ...


@dataclass(slots=True)
class HomeAssistantCommandClient(Generic[RequestT]):
    """Execute mapped commands through Home Assistant.

    This class owns no vendor policy and no entity mapping. Both are supplied by
    the injected mapper, allowing the same execution client to support Pentair
    today and other Home Assistant-backed providers later.
    """

    executor: HomeAssistantServiceExecutor
    mapper: HomeAssistantCommandMapper[RequestT]

    def execute(
        self,
        request: RequestT,
        *,
        timeout: float | None = None,
    ) -> PentairCommandResponse:
        call = self.mapper.map_command(request)
        try:
            result = self.executor.call_service(call, timeout=timeout)
        except HomeAssistantExecutorTimeoutError as exc:
            raise PentairCommandTimeoutError(str(exc)) from exc
        except HomeAssistantExecutorError as exc:
            raise PentairCommandClientError(str(exc)) from exc

        return PentairCommandResponse(
            accepted=result.accepted,
            acknowledged=result.acknowledged,
            message=result.message,
            command_id=result.call_id,
            received_at=result.received_at,
            details={
                "home_assistant": {
                    "domain": call.domain,
                    "service": call.service,
                    "target": call.target,
                    "data": call.data,
                    "context": call.context,
                    "result": result.details,
                }
            },
        )


PentairHomeAssistantCommandClient = HomeAssistantCommandClient[PentairCommandRequest]
