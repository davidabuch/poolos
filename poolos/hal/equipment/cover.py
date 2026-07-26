"""Vendor-neutral pool cover interface."""
from __future__ import annotations

from abc import abstractmethod
from typing import Optional

from ..base import CommandReceipt, HardwareEquipment


class Cover(HardwareEquipment):
    @abstractmethod
    def open(self) -> CommandReceipt: ...

    @abstractmethod
    def close(self) -> CommandReceipt: ...

    @abstractmethod
    def stop(self) -> CommandReceipt: ...

    @abstractmethod
    def position(self) -> Optional[float]: ...
