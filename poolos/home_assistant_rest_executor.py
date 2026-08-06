"""Production-capable Home Assistant REST executor for transport delivery.

Milestone 10.19A provides a synchronous callable compatible with
``HomeAssistantTransportAdapter``. It performs one authenticated REST service
request and returns transport evidence only. It owns no PoolOS policy, retry,
backoff, connection lifecycle, state observation, reconciliation, or live-mode
enablement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import socket
from typing import Any, Callable, Mapping, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener

from .home_assistant_transport_adapter import HomeAssistantServiceCall


class HomeAssistantRestExecutorError(RuntimeError):
    """Base class for sanitized Home Assistant REST executor failures."""


class HomeAssistantRestAuthenticationError(HomeAssistantRestExecutorError):
    """Raised when Home Assistant rejects the configured credential."""


class HomeAssistantRestAuthorizationError(HomeAssistantRestExecutorError):
    """Raised when the credential cannot invoke the requested service."""


class HomeAssistantRestServiceError(HomeAssistantRestExecutorError):
    """Raised when Home Assistant rejects a service request."""


class HomeAssistantRestServerError(HomeAssistantRestExecutorError):
    """Raised when Home Assistant returns a server-side failure."""


class HomeAssistantRestTimeoutError(HomeAssistantRestExecutorError):
    """Raised when the REST request exceeds its configured timeout."""


class HomeAssistantRestConnectionError(HomeAssistantRestExecutorError):
    """Raised when Home Assistant cannot be reached."""


class HomeAssistantRestResponseError(HomeAssistantRestExecutorError):
    """Raised when Home Assistant returns an unusable response."""


class HomeAssistantHttpResponse(Protocol):
    """Minimal response contract required by the executor."""

    status: int
    headers: Mapping[str, str]

    def read(self) -> bytes: ...

    def __enter__(self) -> HomeAssistantHttpResponse: ...

    def __exit__(self, *args: object) -> None: ...


HomeAssistantHttpSender = Callable[[Request, float], HomeAssistantHttpResponse]


@dataclass(frozen=True, slots=True)
class HomeAssistantRestExecutorConfig:
    """Immutable non-secret and secret configuration for one REST endpoint."""

    base_url: str
    access_token: str = field(repr=False)
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        base_url = self.base_url.strip().rstrip("/")
        if not base_url:
            raise ValueError("base_url must not be empty")
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must use http or https")
        token = self.access_token.strip()
        if not token:
            raise ValueError("access_token must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(self, "access_token", token)


@dataclass(frozen=True, slots=True)
class HomeAssistantRestExecutor:
    """Execute one prepared Home Assistant service call through REST."""

    config: HomeAssistantRestExecutorConfig
    sender: HomeAssistantHttpSender | None = field(default=None, repr=False)

    def __call__(self, call: HomeAssistantServiceCall) -> Mapping[str, Any]:
        """Send one service call and return canonical transport evidence."""

        if not isinstance(call, HomeAssistantServiceCall):
            raise TypeError("call must be HomeAssistantServiceCall")
        request = self._build_request(call)
        sender = self.sender or self._default_sender
        try:
            with sender(request, self.config.timeout_seconds) as response:
                status = response.status
                headers = response.headers
                body = response.read()
        except HTTPError as exc:
            self._raise_http_error(exc)
        except (TimeoutError, socket.timeout) as exc:
            raise HomeAssistantRestTimeoutError(
                "Home Assistant REST request timed out"
            ) from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise HomeAssistantRestTimeoutError(
                    "Home Assistant REST request timed out"
                ) from exc
            raise HomeAssistantRestConnectionError(
                "Home Assistant REST connection failed"
            ) from exc
        except OSError as exc:
            raise HomeAssistantRestConnectionError(
                "Home Assistant REST connection failed"
            ) from exc

        if not 200 <= status < 300:
            self._raise_status_error(status)
        parsed = self._parse_body(body)
        return {
            "accepted": True,
            "http_status": status,
            "context_id": self._context_id(headers, parsed),
            "response": parsed,
            "service_call_id": call.service_call_id,
        }

    def _build_request(self, call: HomeAssistantServiceCall) -> Request:
        domain = quote(call.domain, safe="")
        service = quote(call.service, safe="")
        url = f"{self.config.base_url}/api/services/{domain}/{service}"
        payload = {**dict(call.target), **dict(call.data)}
        return Request(
            url,
            data=json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
                "utf-8"
            ),
            headers={
                "Authorization": f"Bearer {self.config.access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

    @staticmethod
    def _default_sender(request: Request, timeout: float) -> HomeAssistantHttpResponse:
        opener = build_opener()
        return cast(HomeAssistantHttpResponse, opener.open(request, timeout=timeout))

    @staticmethod
    def _parse_body(body: bytes) -> Any:
        if not body.strip():
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HomeAssistantRestResponseError(
                "Home Assistant REST response was not valid JSON"
            ) from exc

    @staticmethod
    def _context_id(headers: Mapping[str, str], body: Any) -> str | None:
        lowered = {str(key).lower(): value for key, value in headers.items()}
        for name in ("x-request-id", "x-correlation-id"):
            value = lowered.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        if isinstance(body, Mapping):
            context = body.get("context")
            if isinstance(context, Mapping):
                value = context.get("id")
                if isinstance(value, str) and value.strip():
                    return value.strip()
        if isinstance(body, list):
            for item in body:
                if isinstance(item, Mapping):
                    context = item.get("context")
                    if isinstance(context, Mapping):
                        value = context.get("id")
                        if isinstance(value, str) and value.strip():
                            return value.strip()
        return None

    @staticmethod
    def _raise_http_error(error: HTTPError) -> None:
        HomeAssistantRestExecutor._raise_status_error(error.code)

    @staticmethod
    def _raise_status_error(status: int) -> None:
        if status == 401:
            raise HomeAssistantRestAuthenticationError(
                "Home Assistant REST authentication failed"
            )
        if status == 403:
            raise HomeAssistantRestAuthorizationError(
                "Home Assistant REST authorization failed"
            )
        if 400 <= status < 500:
            raise HomeAssistantRestServiceError(
                f"Home Assistant REST service request was rejected with HTTP {status}"
            )
        if status >= 500:
            raise HomeAssistantRestServerError(
                f"Home Assistant REST server returned HTTP {status}"
            )
        raise HomeAssistantRestResponseError(
            f"Home Assistant REST returned unexpected HTTP {status}"
        )
