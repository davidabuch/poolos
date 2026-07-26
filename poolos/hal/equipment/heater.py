"""Vendor-neutral heater interface."""
from __future__ import annotations

from abc import abstractmethod
from typing import Optional

from ..base import CommandReceipt, HardwareEquipment


class Heater(HardwareEquipment):
    @abstractmethod
    def enable(self) -> CommandReceipt: ...

    @abstractmethod
    def disable(self) -> CommandReceipt: ...

    @abstractmethod
    def set_target_temperature(self, temperature: float) -> CommandReceipt: ...

    @abstractmethod
    def water_temperature(self) -> Optional[float]: ...

    @abstractmethod
    def is_heating(self) -> Optional[bool]: ...
