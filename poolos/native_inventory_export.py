"""Deterministic privacy-safe file export for native IntelliCenter inventory."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping

from .intellicenter_readonly import NativeIntelliCenterTransportSnapshot

NATIVE_INVENTORY_EXPORT_FILENAME = "native_intellicenter_inventory.json"
NATIVE_INVENTORY_EXPORT_SCHEMA_VERSION = 2
NATIVE_INVENTORY_EXPORT_ATTRIBUTE_LIMIT = 64
NATIVE_INVENTORY_EXPORT_SCALAR_TEXT_LIMIT = 256
NATIVE_INVENTORY_REDACTED_VALUE = "[REDACTED]"

_GLOBAL_SENSITIVE_ATTRIBUTE_NAMES = frozenset(
    {
        "ADDRESS",
        "APIKEY",
        "API_KEY",
        "CITY",
        "COUNTRY",
        "EMAIL",
        "EMAIL2",
        "LOCX",
        "LOCY",
        "PASSCODE",
        "PASSWRD",
        "PASSWORD",
        "PHONE",
        "PHONE2",
        "PIN",
        "SECRET",
        "STATE",
        "TOKEN",
        "ZIP",
    }
)
_SYSTEM_SENSITIVE_ATTRIBUTE_NAMES = frozenset(
    {
        "NAME",
        "PROPNAME",
        "SNAME",
        "START",
        "STOP",
    }
)


class NativeIntelliCenterInventoryExporter:
    """Atomically replace one human-readable, non-authoritative inventory file."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.last_exported_at: datetime | None = None
        self.last_error: str | None = None
        self.exports_written = 0

    @property
    def path(self) -> Path:
        return self.root / NATIVE_INVENTORY_EXPORT_FILENAME

    def export(
        self,
        snapshot: NativeIntelliCenterTransportSnapshot,
        *,
        exported_at: datetime,
        transport_metadata: Mapping[str, Any],
    ) -> None:
        if exported_at.tzinfo is None or exported_at.utcoffset() is None:
            raise ValueError("inventory exported_at must be timezone-aware")
        payload = inventory_export_payload(
            snapshot,
            exported_at=exported_at,
            transport_metadata=transport_metadata,
        )
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ) + "\n"
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        try:
            temporary.write_text(encoded, encoding="utf-8")
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self.last_exported_at = exported_at
        self.last_error = None
        self.exports_written += 1

    def diagnostics(self) -> Mapping[str, object]:
        return {
            "export_path": str(self.path),
            "exports_written_this_runtime": self.exports_written,
            "last_exported_at": (
                None if self.last_exported_at is None else self.last_exported_at.isoformat()
            ),
            "last_error": self.last_error,
            "schema_version": NATIVE_INVENTORY_EXPORT_SCHEMA_VERSION,
            "privacy_redaction_enabled": True,
            "authority": "none",
            "command_delivery_enabled": False,
            "read_only_safety_mode": True,
        }


def inventory_export_payload(
    snapshot: NativeIntelliCenterTransportSnapshot,
    *,
    exported_at: datetime,
    transport_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the complete deterministic inventory payload with privacy redaction."""

    if exported_at.tzinfo is None or exported_at.utcoffset() is None:
        raise ValueError("inventory exported_at must be timezone-aware")
    allowed_metadata = {
        key: transport_metadata.get(key)
        for key in (
            "selected_transport",
            "software_version",
            "discovery_generation",
            "reconnect_count",
        )
    }
    objects = [_export_object(item) for item in snapshot.raw_inventory]
    redacted_attribute_count = sum(
        int(item["redacted_attribute_count"]) for item in objects
    )
    return {
        "schema_version": NATIVE_INVENTORY_EXPORT_SCHEMA_VERSION,
        "exported_at": exported_at.isoformat(),
        "snapshot_observed_at": snapshot.observed_at.isoformat(),
        "source_id": snapshot.source_id,
        "connected": snapshot.connected,
        "temperature_unit": snapshot.temperature_unit,
        "authority": "none",
        "authoritative_source": "home_assistant",
        "command_delivery_enabled": False,
        "physical_delivery_enabled": False,
        "read_only_safety_mode": True,
        "privacy_redaction_enabled": True,
        "redacted_attribute_count": redacted_attribute_count,
        "transport": allowed_metadata,
        "object_count": len(snapshot.raw_inventory),
        "objects": objects,
    }


def _export_object(item: Any) -> dict[str, Any]:
    object_type = str(item.object_type).strip().upper()
    exported_attributes: dict[str, str | int | float | bool | None] = {}
    redacted_count = 0
    for attribute in item.attributes[:NATIVE_INVENTORY_EXPORT_ATTRIBUTE_LIMIT]:
        name = str(attribute.name)[:48]
        if _attribute_is_sensitive(object_type, name):
            exported_attributes[name] = NATIVE_INVENTORY_REDACTED_VALUE
            redacted_count += 1
        else:
            exported_attributes[name] = _scalar(attribute.value)
    return {
        "native_id": item.native_id[:64],
        "object_type": item.object_type[:32],
        "subtype": _text(item.subtype, 48),
        "name": (
            NATIVE_INVENTORY_REDACTED_VALUE
            if object_type == "SYSTEM" and item.name is not None
            else _text(item.name, 64)
        ),
        "parent_id": _text(item.parent_id, 64),
        "observed_at": item.observed_at.isoformat(),
        "attribute_count": len(item.attributes),
        "attributes_truncated": len(item.attributes)
        > NATIVE_INVENTORY_EXPORT_ATTRIBUTE_LIMIT,
        "redacted_attribute_count": redacted_count,
        "attributes": exported_attributes,
    }


def _attribute_is_sensitive(object_type: str, name: str) -> bool:
    normalized = name.strip().upper()
    if normalized in _GLOBAL_SENSITIVE_ATTRIBUTE_NAMES:
        return True
    return object_type == "SYSTEM" and normalized in _SYSTEM_SENSITIVE_ATTRIBUTE_NAMES


def _text(value: str | None, limit: int) -> str | None:
    return None if value is None else value[:limit]


def _scalar(value: Any) -> str | int | float | bool | None:
    if isinstance(value, str):
        return value[:NATIVE_INVENTORY_EXPORT_SCALAR_TEXT_LIMIT]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)[:NATIVE_INVENTORY_EXPORT_SCALAR_TEXT_LIMIT]


__all__ = [
    "NATIVE_INVENTORY_EXPORT_ATTRIBUTE_LIMIT",
    "NATIVE_INVENTORY_EXPORT_FILENAME",
    "NATIVE_INVENTORY_EXPORT_SCHEMA_VERSION",
    "NATIVE_INVENTORY_REDACTED_VALUE",
    "NativeIntelliCenterInventoryExporter",
    "inventory_export_payload",
]
