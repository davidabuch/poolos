"""Synchronous Home Assistant REST service executor."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener

from .client import HomeAssistantExecutorError, HomeAssistantExecutorTimeoutError
from .models import HomeAssistantServiceCall, HomeAssistantServiceResult


class HomeAssistantHttpResponse(Protocol):
    """Minimal HTTP response contract consumed by the REST executor."""

    status: int
    headers: Mapping[str, str]

    def read(self) -> bytes: ...

    def __enter__(self) -> HomeAssistantHttpResponse: ...

    def __exit__(self, *args: object) -> None: ...


class HomeAssistantHttpOpener(Protocol):
    """Injectable HTTP opener used to isolate network I/O in tests."""

    def open(
        self,
        request: Request,
        timeout: float | None = None,
    ) -> HomeAssistantHttpResponse: ...


@dataclass(slots=True)
class HomeAssistantRestServiceExecutor:
    """Execute Home Assistant service calls through its REST API.

    The executor is transport-only. It does not map vendor commands, discover
    entities, retry requests, or verify resulting equipment state.
    """

    base_url: str
    access_token: str
    timeout: float | None = 10.0
    opener: HomeAssistantHttpOpener | None = None

    def __post_init__(self) -> None:
        self.base_url = self._normalize_base_url(self.base_url)
        self.access_token = self._require_text(self.access_token, "access_token")
        self.timeout = self._validate_timeout(self.timeout)
        if self.opener is None:
            self.opener = build_opener()

    def call_service(
        self,
        call: HomeAssistantServiceCall,
        *,
        timeout: float | None = None,
    ) -> HomeAssistantServiceResult:
        effective_timeout = self.timeout if timeout is None else self._validate_timeout(timeout)
        request = self._build_request(call)

        try:
            assert self.opener is not None
            with self.opener.open(request, timeout=effective_timeout) as response:
                body = response.read()
                status = response.status
                headers = response.headers
        except HTTPError as exc:
            message = self._http_error_message(exc)
            raise HomeAssistantExecutorError(message) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise HomeAssistantExecutorTimeoutError(
                "Home Assistant REST request timed out"
            ) from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise HomeAssistantExecutorTimeoutError(
                    "Home Assistant REST request timed out"
                ) from exc
            raise HomeAssistantExecutorError(
                f"Home Assistant REST request failed: {exc.reason}"
            ) from exc
        except OSError as exc:
            raise HomeAssistantExecutorError(
                f"Home Assistant REST request failed: {exc}"
            ) from exc

        if not 200 <= status < 300:
            raise HomeAssistantExecutorError(
                f"Home Assistant REST request returned HTTP {status}"
            )

        parsed_body = self._parse_response_body(body)
        call_id = self._extract_call_id(headers, parsed_body)
        return HomeAssistantServiceResult(
            accepted=True,
            acknowledged=True,
            message=f"Home Assistant service call completed with HTTP {status}",
            call_id=call_id,
            received_at=datetime.now(timezone.utc),
            details={
                "http_status": status,
                "response": parsed_body,
                "context": dict(call.context),
            },
        )

    def _build_request(self, call: HomeAssistantServiceCall) -> Request:
        payload = self._service_payload(call)
        domain = quote(call.domain, safe="")
        service = quote(call.service, safe="")
        url = f"{self.base_url}/api/services/{domain}/{service}"
        return Request(
            url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

    @staticmethod
    def _service_payload(call: HomeAssistantServiceCall) -> dict[str, Any]:
        overlap = set(call.target).intersection(call.data)
        if overlap:
            names = ", ".join(sorted(overlap))
            raise ValueError(
                "Home Assistant target and data contain duplicate keys: " + names
            )
        return {**call.target, **call.data}

    @staticmethod
    def _parse_response_body(body: bytes) -> Any:
        if not body.strip():
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HomeAssistantExecutorError(
                "Home Assistant REST response was not valid JSON"
            ) from exc

    @staticmethod
    def _extract_call_id(headers: Mapping[str, str], body: Any) -> str | None:
        for name in ("X-Request-ID", "X-Correlation-ID"):
            value = headers.get(name) or headers.get(name.lower())
            if value and value.strip():
                return value.strip()
        if isinstance(body, Mapping):
            context = body.get("context")
            if isinstance(context, Mapping):
                value = context.get("id")
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    @staticmethod
    def _http_error_message(error: HTTPError) -> str:
        detail = ""
        try:
            raw = error.read()
            if raw:
                parsed = json.loads(raw.decode("utf-8"))
                detail = f": {parsed}"
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            detail = ""
        return f"Home Assistant REST request returned HTTP {error.code}{detail}"

    @staticmethod
    def _normalize_base_url(value: str) -> str:
        normalized = HomeAssistantRestServiceExecutor._require_text(value, "base_url")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("base_url must use http or https")
        return normalized.rstrip("/")

    @staticmethod
    def _validate_timeout(value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("timeout must be greater than zero when provided")
        return value

    @staticmethod
    def _require_text(value: str, label: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{label} must not be empty")
        return normalized
