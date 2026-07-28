"""Canonical operation translation boundary.

This module deliberately stops at ``TranslationResult``. Delivery of vendor
commands belongs to a later adapter/gateway layer so translation remains pure,
deterministic, and independently testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .context import TranslationContext
from .operations import PoolOperation
from .registry import TranslatorRegistry
from .response import TranslationResult


TranslationContextProvider = Callable[[PoolOperation], TranslationContext]


@dataclass(slots=True)
class OperationTranslationHandler:
    """Translate one canonical operation using resolved installation context.

    The context provider owns equipment-to-installation routing. The handler
    therefore contains no vendor-specific branching and can support multiple
    vendors through one ``TranslatorRegistry``.
    """

    registry: TranslatorRegistry
    context_provider: TranslationContextProvider

    def __call__(self, operation: PoolOperation) -> TranslationResult:
        """Resolve context and translate one operation without delivering it."""

        context = self.context_provider(operation)
        if not isinstance(context, TranslationContext):
            raise TypeError("context_provider must return TranslationContext")
        return self.registry.translate(context.vendor, operation, context)
