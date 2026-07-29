"""In-memory transport used for HAL tests and offline development."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ..exceptions import TransportUnavailableError
from ..transport import Transport, TransportMetadata, TransportResponse, TransportState


class SimulatorTransport(Transport):
    def __init__(self, name: str = "simulator") -> None:
        self._name = name
        self._state = TransportState.DISCONNECTED
        self._store: dict[str, object] = {}
        self._last_contact: Optional[datetime] = None
        self._errors = 0

    def connect(self) -> None:
        self._state = TransportState.CONNECTED
        self._last_contact = datetime.now(timezone.utc)

    def disconnect(self) -> None:
        self._state = TransportState.DISCONNECTED

    def _ensure_connected(self) -> None:
        if self._state is not TransportState.CONNECTED:
            self._errors += 1
            raise TransportUnavailableError("simulator transport is disconnected")

    def send(self, destination: str, payload: object, *, timeout: Optional[float] = None) -> TransportResponse:
        self._ensure_connected()
        self._store[destination] = payload
        self._last_contact = datetime.now(timezone.utc)
        return TransportResponse(accepted=True, acknowledged=True, payload=payload)

    def read(self, source: str, *, timeout: Optional[float] = None) -> TransportResponse:
        self._ensure_connected()
        self._last_contact = datetime.now(timezone.utc)
        return TransportResponse(accepted=True, acknowledged=True, payload=self._store.get(source))

    def metadata(self) -> TransportMetadata:
        return TransportMetadata(
            name=self._name,
            version="1.0",
            state=self._state,
            last_contact=self._last_contact,
            error_count=self._errors,
        )
