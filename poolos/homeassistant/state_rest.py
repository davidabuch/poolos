"""Synchronous Home Assistant REST state publication executor."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener

from .client import HomeAssistantExecutorError, HomeAssistantExecutorTimeoutError
from .publication import (
    HomeAssistantStatePublication,
    HomeAssistantStatePublicationResult,
)


class HomeAssistantStateHttpResponse(Protocol):
    status: int
    headers: Mapping[str, str]

    def read(self) -> bytes: ...

    def __enter__(self) -> HomeAssistantStateHttpResponse: ...

    def __exit__(self, *args: object) -> None: ...


class HomeAssistantStateHttpOpener(Protocol):
    def open(
        self,
        request: Request,
        timeout: float | None = None,
    ) -> HomeAssistantStateHttpResponse: ...


@dataclass(slots=True)
class HomeAssistantRestStatePublicationExecutor:
    """Publish dedicated simulated entities through Home Assistant's state API."""

    base_url: str
    access_token: str
    timeout: float | None = 10.0
    opener: HomeAssistantStateHttpOpener | None = None

    def __post_init__(self) -> None:
        self.base_url = self._require_text(self.base_url, "base_url").rstrip("/")
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must use http or https")
        self.access_token = self._require_text(self.access_token, "access_token")
        self.timeout = self._validate_timeout(self.timeout)
        if self.opener is None:
            self.opener = cast(HomeAssistantStateHttpOpener, build_opener())

    def publish_state(
        self,
        publication: HomeAssistantStatePublication,
        *,
        timeout: float | None = None,
    ) -> HomeAssistantStatePublicationResult:
        effective_timeout = self.timeout if timeout is None else self._validate_timeout(timeout)
        request = self._build_request(publication)
        try:
            assert self.opener is not None
            with self.opener.open(request, timeout=effective_timeout) as response:
                status = response.status
                body = response.read()
        except HTTPError as exc:
            raise HomeAssistantExecutorError(
                f"Home Assistant state publication returned HTTP {exc.code}"
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise HomeAssistantExecutorTimeoutError(
                "Home Assistant state publication timed out"
            ) from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise HomeAssistantExecutorTimeoutError(
                    "Home Assistant state publication timed out"
                ) from exc
            raise HomeAssistantExecutorError(
                f"Home Assistant state publication failed: {exc.reason}"
            ) from exc
        except OSError as exc:
            raise HomeAssistantExecutorError(
                f"Home Assistant state publication failed: {exc}"
            ) from exc

        if not 200 <= status < 300:
            raise HomeAssistantExecutorError(
                f"Home Assistant state publication returned HTTP {status}"
            )
        details: dict[str, Any] = {"http_status": status}
        if body.strip():
            try:
                details["response"] = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise HomeAssistantExecutorError(
                    "Home Assistant state publication response was not valid JSON"
                ) from exc
        return HomeAssistantStatePublicationResult(
            accepted=True,
            entity_id=publication.entity_id,
            received_at=datetime.now(timezone.utc),
            details=details,
        )

    def _build_request(self, publication: HomeAssistantStatePublication) -> Request:
        entity_id = quote(publication.entity_id, safe="")
        payload = {
            "state": publication.state,
            "attributes": dict(publication.attributes),
        }
        return Request(
            f"{self.base_url}/api/states/{entity_id}",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

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
