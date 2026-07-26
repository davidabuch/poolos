"""Vendor-neutral filter interface.

Filter health is intentionally absent: it is derived by PoolOS rather than
reported as a hardware capability.
"""
from __future__ import annotations

from abc import abstractmethod
from datetime import datetime
from typing import Optional

from ..base import HardwareEquipment


class Filter(HardwareEquipment):
    @abstractmethod
    def pressure_psi(self) -> Optional[float]: ...

    @abstractmethod
    def flow_gpm(self) -> Optional[float]: ...

    @abstractmethod
    def runtime_hours(self) -> Optional[float]: ...

    @abstractmethod
    def last_cleaned_at(self) -> Optional[datetime]: ...
