"""Registry for writable vendor command endpoints."""

from __future__ import annotations

from dataclasses import dataclass, field

from .endpoint import VendorCommandEndpoint
from .exceptions import DuplicateEndpointError, EndpointNotFoundError


@dataclass(slots=True)
class EndpointRegistry:
    """Register endpoints by stable controller identity."""

    _endpoints: dict[str, VendorCommandEndpoint] = field(default_factory=dict)

    def register(self, endpoint: VendorCommandEndpoint) -> None:
        endpoint_id = self._normalize_endpoint_id(endpoint.endpoint_id)
        self._normalize_vendor(endpoint.vendor)
        if endpoint_id in self._endpoints:
            raise DuplicateEndpointError(endpoint_id)
        self._endpoints[endpoint_id] = endpoint

    def replace(self, endpoint: VendorCommandEndpoint) -> None:
        endpoint_id = self._normalize_endpoint_id(endpoint.endpoint_id)
        self._normalize_vendor(endpoint.vendor)
        self._endpoints[endpoint_id] = endpoint

    def unregister(self, endpoint_id: str) -> VendorCommandEndpoint:
        key = self._normalize_endpoint_id(endpoint_id)
        try:
            return self._endpoints.pop(key)
        except KeyError as exc:
            raise EndpointNotFoundError(key) from exc

    def get(self, endpoint_id: str) -> VendorCommandEndpoint:
        key = self._normalize_endpoint_id(endpoint_id)
        try:
            return self._endpoints[key]
        except KeyError as exc:
            raise EndpointNotFoundError(key) from exc

    def all(self) -> tuple[VendorCommandEndpoint, ...]:
        return tuple(self._endpoints.values())

    @staticmethod
    def _normalize_endpoint_id(endpoint_id: str) -> str:
        normalized = endpoint_id.strip()
        if not normalized:
            raise ValueError("endpoint_id must not be empty")
        return normalized

    @staticmethod
    def _normalize_vendor(vendor: str) -> str:
        normalized = vendor.strip().lower()
        if not normalized:
            raise ValueError("endpoint vendor must not be empty")
        return normalized
