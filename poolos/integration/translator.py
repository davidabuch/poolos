"""Protocol implemented by all vendor translators."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .context import TranslationContext
from .operations import PoolOperation
from .response import TranslationResult


@runtime_checkable
class Translator(Protocol):
    """Translate canonical PoolOS operations into vendor commands."""

    @property
    def vendor(self) -> str:
        """Return the stable vendor identifier handled by this translator."""
        ...

    def supports(self, operation: PoolOperation) -> bool:
        """Return whether the translator recognizes an operation type."""
        ...

    def translate(
        self,
        operation: PoolOperation,
        context: TranslationContext,
    ) -> TranslationResult:
        """Translate an operation using only immutable context facts."""
        ...
