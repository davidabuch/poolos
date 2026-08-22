"""Executable regression for native IntelliCenter target publication."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from poolos.intellicenter_readonly import NativeIntelliCenterReadAdapter


ROOT = Path(__file__).resolve().parents[1]


def _load_test_harness(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "tests" / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_subscription_sensitive_lotmp_push_reaches_native_climate_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The narrow BODY subscription must publish prompt LOTMP end to end."""

    transport_harness = _load_test_harness(
        "poolos_target_transport_harness",
        "test_independent_intellicenter_transport.py",
    )
    climate_harness = _load_test_harness(
        "poolos_target_climate_harness",
        "test_home_assistant_native_climate.py",
    )
    transport_module = transport_harness._load_module(monkeypatch)
    climate_module = climate_harness._load_executable_climate_module()

    transport_harness.FakeModelController.initial_objects = (
        transport_harness._objects()
        + (
            (
                "B1202",
                {
                    "OBJTYP": "BODY",
                    "SUBTYP": "SPA",
                    "SNAME": "Spa",
                    "PARENT": "SYS01",
                    "STATUS": "OFF",
                    "HTMODE": "0",
                    "LSTTMP": "89",
                    "LOTMP": "96",
                    "SETPT": "96",
                    "SETTMP": "96",
                    "HEATER": "H0001",
                },
            ),
        )
    )

    async def exercise() -> None:
        transport = transport_module.IndependentIntelliCenterReadOnlyTransport(
            host="192.0.2.10"
        )
        assert transport._model.attribute_map["BODY"] == {
            "SNAME",
            "HEATER",
            "HITMP",
            "HTMODE",
            "LOTMP",
            "LSTTMP",
            "MODE",
            "STATUS",
            "VOL",
        }
        assert "SETTMP" not in transport._model.attribute_map["BODY"]
        assert "SETPT" not in transport._model.attribute_map["BODY"]
        await transport.async_start()

        for _ in range(20):
            await asyncio.sleep(0)
            if (
                not transport._connection_reconciliation_tasks
                and not transport._body_metadata_refresh_tasks
            ):
                break

        initial_transport_snapshot = transport.latest_snapshot
        assert initial_transport_snapshot is not None

        coordinator = SimpleNamespace(
            native_intellicenter_snapshot=NativeIntelliCenterReadAdapter().map_snapshot(
                initial_transport_snapshot,
                generated_at=initial_transport_snapshot.observed_at,
            )
        )
        manual = SimpleNamespace(available=True)
        entry = SimpleNamespace(
            runtime_data=SimpleNamespace(manual_intellicenter=manual),
            entry_id="target_lifecycle",
        )
        description = next(
            item for item in climate_module.CLIMATE_DESCRIPTIONS if item.key == "spa"
        )
        entity = climate_module.PoolOSNativeClimate(
            coordinator,
            entry,
            description,
        )
        assert entity.target_temperature == 96.0

        published_snapshots: list[object] = []
        published_targets: list[float | None] = []

        def publish_latest_snapshot() -> None:
            latest = transport.latest_snapshot
            assert latest is not None
            coordinator.native_intellicenter_snapshot = (
                NativeIntelliCenterReadAdapter().map_snapshot(
                    latest,
                    generated_at=latest.observed_at,
                )
            )
            published_snapshots.append(latest)
            published_targets.append(entity.target_temperature)

        transport._set_snapshot_update_callback(publish_latest_snapshot)

        # The live A/B trace proved this narrow subscription produces LOTMP
        # NotifyList updates. Exercise pyintellicenter's real mutation/callback
        # shape while stale auxiliary values remain in the cached model.
        transport._controller._apply_updates(
            [{"objnam": "B1202", "params": {"LOTMP": "97"}}]
        )
        transport._controller._apply_updates(
            [{"objnam": "B1202", "params": {"LOTMP": "98"}}]
        )

        assert len(published_snapshots) == 2
        assert published_snapshots[0] is not initial_transport_snapshot
        assert published_snapshots[1] is transport.latest_snapshot
        assert published_targets == [97.0, 98.0]
        assert entity.target_temperature == 98.0

        latest = transport.latest_snapshot
        assert latest is not None
        spa = next(body for body in latest.bodies if body.native_id == "B1202")
        assert spa.target_temperature == 98.0

        await transport.async_stop()

    asyncio.run(exercise())
