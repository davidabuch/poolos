"""Vendor-neutral light interface."""
from __future__ import annotations

from abc import abstractmethod
from typing import Optional

from ..base import CommandReceipt, HardwareEquipment


class Light(HardwareEquipment):
    @abstractmethod
    def turn_on(self) -> CommandReceipt: ...

    @abstractmethod
    def turn_off(self) -> CommandReceipt: ...

    def set_brightness(self, brightness: int) -> CommandReceipt:
        from ...capabilities import Capability
        self.require(Capability.BRIGHTNESS_CONTROL)
        if not 0 <= brightness <= 100:
            raise ValueError("brightness must be between 0 and 100")
        return self._set_brightness(brightness)

    def _set_brightness(self, brightness: int) -> CommandReceipt:
        raise NotImplementedError

    def set_color(self, color: str | tuple[int, int, int]) -> CommandReceipt:
        from ...capabilities import Capability
        self.require(Capability.COLOR_CONTROL)
        return self._set_color(color)

    def _set_color(self, color: str | tuple[int, int, int]) -> CommandReceipt:
        raise NotImplementedError

    def set_effect(self, effect: str) -> CommandReceipt:
        from ...capabilities import Capability
        self.require(Capability.EFFECT_CONTROL)
        return self._set_effect(effect)

    def _set_effect(self, effect: str) -> CommandReceipt:
        raise NotImplementedError
