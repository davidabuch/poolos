"""Vendor-neutral valve interface."""
from __future__ import annotations

from abc import abstractmethod
from typing import Optional

from ..base import CommandReceipt, HardwareEquipment


class Valve(HardwareEquipment):
    @abstractmethod
    def move_to(self, position: float | str) -> CommandReceipt: ...

    @abstractmethod
    def position(self) -> Optional[float | str]: ...

    @abstractmethod
    def is_moving(self) -> Optional[bool]: ...

    def stop_motion(self) -> CommandReceipt:
        from ...capabilities import Capability
        self.require(Capability.VALVE_STOP)
        return self._stop_motion()

    def _stop_motion(self) -> CommandReceipt:
        raise NotImplementedError
