"""Deterministic file export for complete native IntelliCenter inventory."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping

from .intellicenter_readonly import NativeIntelliCenterTransportSnapshot

NATIVE_INVENTORY_EXPORT_FILENAME = "native_intellicenter_inventory.json"
NATIVE_INVENTORY_EXPORT_SCHEMA_VERSION = 1
NATIVE_INVENTORY_EXPORT_ATTRIBUTE_LIMIT = 64
NATIVE_INVENTORY_EXPORT_SCALAR_TEXT_LIMIT = 256


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
    """Build the complete deterministic inventory payload without credentials."""

    if exported_at.tzinfo is None or exported_at.utcoffset() is None:
        raise ValueError("inventory exported_at must be timezone-aware")
    allowed_metadata = {
        key: transport_metadata.get(key)
        for key in (
            "selected_transport",
            "controller_name",
            "software_version",
            "discovery_generation",
            "reconnect_count",
        )
    }
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
        "transport": allowed_metadata,
        "object_count": len(snapshot.raw_inventory),
        "objects": [
            {
                "native_id": item.native_id[:64],
                "object_type": item.object_type[:32],
                "subtype": _text(item.subtype, 48),
                "name": _text(item.name, 64),
                "parent_id": _text(item.parent_id, 64),
                "observed_at": item.observed_at.isoformat(),
                "attribute_count": len(item.attributes),
                "attributes_truncated": len(item.attributes)
                > NATIVE_INVENTORY_EXPORT_ATTRIBUTE_LIMIT,
                "attributes": {
                    attribute.name[:48]: _scalar(attribute.value)
                    for attribute in item.attributes[
                        :NATIVE_INVENTORY_EXPORT_ATTRIBUTE_LIMIT
                    ]
                },
            }
            for item in snapshot.raw_inventory
        ],
    }


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
    "NativeIntelliCenterInventoryExporter",
    "inventory_export_payload",
]
