"""Registry for adapter discovery and hot-swappable transport-backed adapters."""
from __future__ import annotations


from .adapter import HardwareAdapter
from .exceptions import AdapterNotFoundError, DuplicateAdapterError


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, HardwareAdapter] = {}

    def register(self, adapter: HardwareAdapter) -> None:
        key = adapter.metadata.adapter_id
        if key in self._adapters:
            raise DuplicateAdapterError(key)
        self._adapters[key] = adapter

    def replace(self, adapter: HardwareAdapter) -> None:
        self._adapters[adapter.metadata.adapter_id] = adapter

    def unregister(self, adapter_id: str) -> HardwareAdapter:
        try:
            return self._adapters.pop(adapter_id)
        except KeyError as exc:
            raise AdapterNotFoundError(adapter_id) from exc

    def get(self, adapter_id: str) -> HardwareAdapter:
        try:
            return self._adapters[adapter_id]
        except KeyError as exc:
            raise AdapterNotFoundError(adapter_id) from exc

    def all(self) -> tuple[HardwareAdapter, ...]:
        return tuple(self._adapters.values())

    def discover_all(self):
        return tuple(item for adapter in self._adapters.values() for item in adapter.discover())

    def initialize_all(self) -> None:
        for adapter in self._adapters.values():
            adapter.initialize()

    def connect_all(self) -> None:
        for adapter in self._adapters.values():
            adapter.connect()

    def shutdown_all(self) -> None:
        for adapter in reversed(tuple(self._adapters.values())):
            adapter.shutdown()
