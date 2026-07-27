"""Data-driven registry for vendor translator discovery."""

from __future__ import annotations

from dataclasses import dataclass, field

from .context import TranslationContext
from .exceptions import (
    DuplicateTranslatorError,
    TranslatorNotFoundError,
    VendorMismatchError,
)
from .operations import PoolOperation
from .response import TranslationResult
from .translator import Translator


@dataclass(slots=True)
class TranslatorRegistry:
    """Register and invoke translators without hard-coded vendor knowledge."""

    _translators: dict[str, Translator] = field(default_factory=dict)

    def register(self, translator: Translator) -> None:
        vendor = self._normalize_vendor(translator.vendor)
        if vendor in self._translators:
            raise DuplicateTranslatorError(vendor)
        self._translators[vendor] = translator

    def replace(self, translator: Translator) -> None:
        self._translators[self._normalize_vendor(translator.vendor)] = translator

    def unregister(self, vendor: str) -> Translator:
        key = self._normalize_vendor(vendor)
        try:
            return self._translators.pop(key)
        except KeyError as exc:
            raise TranslatorNotFoundError(key) from exc

    def get(self, vendor: str) -> Translator:
        key = self._normalize_vendor(vendor)
        try:
            return self._translators[key]
        except KeyError as exc:
            raise TranslatorNotFoundError(key) from exc

    def all(self) -> tuple[Translator, ...]:
        return tuple(self._translators.values())

    def translate(
        self,
        vendor: str,
        operation: PoolOperation,
        context: TranslationContext,
    ) -> TranslationResult:
        key = self._normalize_vendor(vendor)
        context_vendor = self._normalize_vendor(context.vendor)
        if context_vendor != key:
            raise VendorMismatchError(key, context_vendor)
        return self.get(key).translate(operation, context)

    @staticmethod
    def _normalize_vendor(vendor: str) -> str:
        normalized = vendor.strip().lower()
        if not normalized:
            raise ValueError("vendor must not be empty")
        return normalized
