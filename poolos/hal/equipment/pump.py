"""Vendor-neutral pump interface."""
from __future__ import annotations

from abc import abstractmethod
from typing import Optional

from ..base import CommandReceipt, HardwareEquipment


class Pump(HardwareEquipment):
    @abstractmethod
    def start(self) -> CommandReceipt: ...

    @abstractmethod
    def stop(self) -> CommandReceipt: ...

    def set_speed_rpm(self, rpm: int) -> CommandReceipt:
        from ...capabilities import Capability
        self.require(Capability.RPM_CONTROL)
        return self._set_speed_rpm(rpm)

    @abstractmethod
    def _set_speed_rpm(self, rpm: int) -> CommandReceipt: ...

    def set_flow_gpm(self, gpm: float) -> CommandReceipt:
        from ...capabilities import Capability
        self.require(Capability.FLOW_CONTROL)
        return self._set_flow_gpm(gpm)

    def _set_flow_gpm(self, gpm: float) -> CommandReceipt:
        raise NotImplementedError

    @abstractmethod
    def actual_rpm(self) -> Optional[int]: ...

    @abstractmethod
    def power_watts(self) -> Optional[float]: ...
