"""Future direct RS-485 transport boundary.

No serial library or hardware dongle is assumed by Milestone 10.1.
"""
from __future__ import annotations

from typing import Optional

from ..exceptions import TransportUnavailableError
from ..transport import Transport, TransportMetadata, TransportResponse, TransportState


class RS485Transport(Transport):
    def connect(self) -> None:
        raise TransportUnavailableError("RS-485 transport requires a future hardware implementation")

    def disconnect(self) -> None:
        return None

    def send(self, destination: str, payload: object, *, timeout: Optional[float] = None) -> TransportResponse:
        raise TransportUnavailableError("RS-485 transport requires a future hardware implementation")

    def read(self, source: str, *, timeout: Optional[float] = None) -> TransportResponse:
        raise TransportUnavailableError("RS-485 transport requires a future hardware implementation")

    def metadata(self) -> TransportMetadata:
        return TransportMetadata(name="rs485", version="stub", state=TransportState.DISCONNECTED)
