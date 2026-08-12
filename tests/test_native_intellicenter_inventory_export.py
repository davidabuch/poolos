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
    NATIVE_INVENTORY_EXPORT_SCHEMA_VERSION,
    NATIVE_INVENTORY_REDACTED_VALUE,
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


def _privacy_snapshot() -> NativeIntelliCenterTransportSnapshot:
    return NativeIntelliCenterTransportSnapshot(
        source_id="poolos.independent_intellicenter",
        observed_at=NOW,
        connected=True,
        temperature_unit="°F",
        raw_inventory=(
            NativeRawObject(
                native_id="SYSTEM1",
                object_type="SYSTEM",
                subtype=None,
                name="secret-system-name",
                parent_id=None,
                observed_at=NOW,
                attributes=(
                    NativeRawAttribute("VER", "3.014"),
                    NativeRawAttribute("ADDRESS", "123 Private Street"),
                    NativeRawAttribute("CITY", "Private City"),
                    NativeRawAttribute("STATE", "CA"),
                    NativeRawAttribute("COUNTRY", "United States"),
                    NativeRawAttribute("ZIP", "99999"),
                    NativeRawAttribute("EMAIL", "private@example.com"),
                    NativeRawAttribute("PHONE", "5551234567"),
                    NativeRawAttribute("LOCX", "-118.123"),
                    NativeRawAttribute("LOCY", "34.123"),
                    NativeRawAttribute("NAME", "Private Person"),
                    NativeRawAttribute("PROPNAME", "Private Family"),
                    NativeRawAttribute("SNAME", "opaque-secret-like-value"),
                    NativeRawAttribute("START", "08/12/26"),
                    NativeRawAttribute("STOP", "08/19/26"),
                ),
            ),
            NativeRawObject(
                native_id="PERMIT1",
                object_type="PERMIT",
                subtype="ADV",
                name="Administrator",
                parent_id=None,
                observed_at=NOW,
                attributes=(
                    NativeRawAttribute("PASSWRD", "7777"),
                    NativeRawAttribute("ENABLE", "ON"),
                ),
            ),
            NativeRawObject(
                native_id="TIME1",
                object_type="SYSTIM",
                subtype=None,
                name="System Time",
                parent_id=None,
                observed_at=NOW,
                attributes=(
                    NativeRawAttribute("LOCX", "-118.456"),
                    NativeRawAttribute("LOCY", "34.456"),
                    NativeRawAttribute("ZIP", "90000"),
                    NativeRawAttribute("DAY", "08,12,26"),
                ),
            ),
        ),
    )


def test_complete_export_preserves_all_objects_and_is_deterministic(tmp_path) -> None:
    metadata = {
        "selected_transport": "tcp",
        "controller_name": "Private Family",
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
    assert forward["schema_version"] == NATIVE_INVENTORY_EXPORT_SCHEMA_VERSION
    assert forward["privacy_redaction_enabled"] is True
    assert forward["object_count"] == 84
    assert len(forward["objects"]) == 84
    assert forward["objects"][0]["native_id"] == "OBJ003"
    assert forward["objects"][-1]["native_id"] == "OBJ002"
    assert len(forward["objects"][0]["attributes"]["LONG"]) == 256
    assert "host" not in forward["transport"]
    assert "controller_name" not in forward["transport"]
    assert forward["authority"] == "none"
    assert forward["command_delivery_enabled"] is False

    exporter = NativeIntelliCenterInventoryExporter(tmp_path / "poolos_logs")
    exporter.export(_snapshot(), exported_at=NOW, transport_metadata=metadata)
    path = tmp_path / "poolos_logs" / NATIVE_INVENTORY_EXPORT_FILENAME
    written = json.loads(path.read_text(encoding="utf-8"))

    assert written == forward
    assert not path.with_suffix(".json.tmp").exists()
    assert exporter.diagnostics()["export_path"] == str(path)
    assert exporter.diagnostics()["privacy_redaction_enabled"] is True


def test_sensitive_system_permit_and_location_fields_are_redacted() -> None:
    payload = inventory_export_payload(
        _privacy_snapshot(),
        exported_at=NOW,
        transport_metadata={"controller_name": "Private Family"},
    )
    encoded = json.dumps(payload, sort_keys=True)
    permit, system, systim = payload["objects"]

    assert system["name"] == NATIVE_INVENTORY_REDACTED_VALUE
    assert system["attributes"]["VER"] == "3.014"
    for key in (
        "ADDRESS",
        "CITY",
        "STATE",
        "COUNTRY",
        "ZIP",
        "EMAIL",
        "PHONE",
        "LOCX",
        "LOCY",
        "NAME",
        "PROPNAME",
        "SNAME",
        "START",
        "STOP",
    ):
        assert system["attributes"][key] == NATIVE_INVENTORY_REDACTED_VALUE

    assert permit["name"] == "Administrator"
    assert permit["attributes"]["PASSWRD"] == NATIVE_INVENTORY_REDACTED_VALUE
    assert permit["attributes"]["ENABLE"] == "ON"
    assert systim["attributes"]["LOCX"] == NATIVE_INVENTORY_REDACTED_VALUE
    assert systim["attributes"]["LOCY"] == NATIVE_INVENTORY_REDACTED_VALUE
    assert systim["attributes"]["ZIP"] == NATIVE_INVENTORY_REDACTED_VALUE
    assert systim["attributes"]["DAY"] == "08,12,26"
    assert payload["redacted_attribute_count"] == 18

    for secret in (
        "123 Private Street",
        "Private City",
        "99999",
        "private@example.com",
        "5551234567",
        "Private Person",
        "Private Family",
        "opaque-secret-like-value",
        "7777",
        "-118.456",
        "34.456",
    ):
        assert secret not in encoded


def test_ha_inventory_diagnostics_remain_capped_while_file_export_is_complete() -> None:
    snapshot = _snapshot()
    diagnostics = snapshot.raw_inventory_diagnostics()
    payload = inventory_export_payload(snapshot, exported_at=NOW, transport_metadata={})

    assert diagnostics["displayed_native_object_count"] == 20
    assert diagnostics["inventory_truncated"] is True
    assert len(diagnostics["raw_inventory"]) == 20
    assert len(payload["objects"]) == 84
    assert payload["object_count"] == 84
