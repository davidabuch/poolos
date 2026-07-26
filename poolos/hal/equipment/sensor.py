"""Read-only sensor interface."""
from __future__ import annotations

from abc import abstractmethod
from typing import Optional

from ..base import HardwareEquipment


class Sensor(HardwareEquipment):
    @abstractmethod
    def value(self) -> object: ...

    @abstractmethod
    def unit(self) -> Optional[str]: ...
