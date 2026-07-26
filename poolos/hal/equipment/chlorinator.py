"""Vendor-neutral chlorinator interface."""
from __future__ import annotations

from abc import abstractmethod
from typing import Optional

from ..base import CommandReceipt, HardwareEquipment


class Chlorinator(HardwareEquipment):
    @abstractmethod
    def enable(self) -> CommandReceipt: ...

    @abstractmethod
    def disable(self) -> CommandReceipt: ...

    @abstractmethod
    def set_output_percent(self, percent: float) -> CommandReceipt: ...

    @abstractmethod
    def output_percent(self) -> Optional[float]: ...

    @abstractmethod
    def salt_level_ppm(self) -> Optional[float]: ...

    @abstractmethod
    def cell_status(self) -> Optional[str]: ...
