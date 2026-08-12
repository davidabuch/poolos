"""Complete native inventory export tests for milestone 12.0C2."""

from __future__ import annotations

from datetime import UTC, datetime
import json

from poolos.intellicenter_readonly import (
    NativeIntelliCenterTransportSnapshot,
    NativeRawAttribute,
    NativeRawObject,
)
from poolos.native_inventory_export import (
    NATIVE_INVENTORY_EXPORT_FILENAME,
    NativeIntelliCenterInventoryExporter,
    inventory_export_payload,
)

NOW = datetime(2026, 8, 12, 3, 0, tzinfo=UTC)


def _snapshot(*, reverse: bool = False) -> NativeIntelliCenterTransportSnapshot:
    indexes = tuple(reversed(range(84))) if reverse else tuple(range(84))
    return NativeIntelliCenterTransportSnapshot(
        source_id="poolos.independent_intellicenter",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        raw_inventory=tuple(
            NativeRawObject(
                native_id=f"OBJ{index:03d}",
                object_type="SENSE" if index < 3 else "FUTURE",
                subtype="POOL" if index == 0 else "UNKNOWN",
                name=f"Object {index}",
                parent_id="SYS01",
                observed_at=NOW,
                attributes=(
                    NativeRawAttribute("SOURCE", index),
                    NativeRawAttribute("LONG", "x" * 400),
                ),
            )
            for index in indexes
        ),
    )


def test_complete_export_preserves_all_objects_and_is_deterministic(tmp_path) -> None:
    metadata = {
        "selected_transport": "tcp",
        "controller_name": "Buch Family",
        "software_version": "3.014",
        "discovery_generation": 1,
        "reconnect_count": 0,
        "host": "must-not-export",
    }
    forward = inventory_export_payload(
        _snapshot(), exported_at=NOW, transport_metadata=metadata
    )
    reverse = inventory_export_payload(
        _snapshot(reverse=True), exported_at=NOW, transport_metadata=metadata
    )

    assert forward == reverse
    assert forward["object_count"] == 84
    assert len(forward["objects"]) == 84
    assert forward["objects"][0]["native_id"] == "OBJ003"
    assert forward["objects"][-1]["native_id"] == "OBJ002"
    assert len(forward["objects"][0]["attributes"]["LONG"]) == 256
    assert "host" not in forward["transport"]
    assert forward["authority"] == "none"
    assert forward["command_delivery_enabled"] is False

    exporter = NativeIntelliCenterInventoryExporter(tmp_path / "poolos_logs")
    exporter.export(_snapshot(), exported_at=NOW, transport_metadata=metadata)
    path = tmp_path / "poolos_logs" / NATIVE_INVENTORY_EXPORT_FILENAME
    written = json.loads(path.read_text(encoding="utf-8"))

    assert written == forward
    assert not path.with_suffix(".json.tmp").exists()
    assert exporter.diagnostics()["export_path"] == str(path)


def test_ha_inventory_diagnostics_remain_capped_while_file_export_is_complete() -> None:
    snapshot = _snapshot()
    diagnostics = snapshot.raw_inventory_diagnostics()
    payload = inventory_export_payload(snapshot, exported_at=NOW, transport_metadata={})

    assert diagnostics["displayed_native_object_count"] == 20
    assert diagnostics["inventory_truncated"] is True
    assert len(diagnostics["raw_inventory"]) == 20
    assert len(payload["objects"]) == 84
    assert payload["object_count"] == 84
