"""Home Assistant transport contract placeholder.

The concrete implementation belongs in a later transport milestone. Keeping
this explicit stub prevents HAL consumers from depending on Home Assistant.
"""
from __future__ import annotations

from typing import Optional

from ..exceptions import TransportUnavailableError
from ..transport import Transport, TransportMetadata, TransportResponse, TransportState


class HomeAssistantTransport(Transport):
    def connect(self) -> None:
        raise TransportUnavailableError("Home Assistant transport is not implemented in HAL 10.1")

    def disconnect(self) -> None:
        return None

    def send(self, destination: str, payload: object, *, timeout: Optional[float] = None) -> TransportResponse:
        raise TransportUnavailableError("Home Assistant transport is not implemented in HAL 10.1")

    def read(self, source: str, *, timeout: Optional[float] = None) -> TransportResponse:
        raise TransportUnavailableError("Home Assistant transport is not implemented in HAL 10.1")

    def metadata(self) -> TransportMetadata:
        return TransportMetadata(name="homeassistant", version="stub", state=TransportState.DISCONNECTED)
