"""Pentair translator scaffold for Milestone 10.3.1."""

from __future__ import annotations

from dataclasses import dataclass

from ..context import TranslationContext
from ..exceptions import UnsupportedOperationError, VendorMismatchError
from ..operations import PoolOperation, SetHeatMode, SetPumpSpeed, StartPump, StopPump
from ..response import TranslationResult


@dataclass(frozen=True, slots=True)
class PentairTranslator:
    """Recognize initial PoolOS operations before concrete mapping is added."""

    vendor: str = "pentair"

    _recognized_types = (SetPumpSpeed, StartPump, StopPump, SetHeatMode)

    def supports(self, operation: PoolOperation) -> bool:
        return isinstance(operation, self._recognized_types)

    def translate(
        self,
        operation: PoolOperation,
        context: TranslationContext,
    ) -> TranslationResult:
        if context.vendor.strip().lower() != self.vendor:
            raise VendorMismatchError(self.vendor, context.vendor.strip().lower())
        # Concrete mappings begin in Milestone 10.3.2. The scaffold fails closed
        # rather than fabricating a transport or protocol command.
        raise UnsupportedOperationError(self.vendor, type(operation))
