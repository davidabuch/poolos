"""Exact-boundary tests for the HA confirmed-outage delivery adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from poolos.grid_outage_physical_safety import (
    GridOutageReductionCandidate,
    GridOutageReductionKind,
)
from poolos.physical_command_authority import PhysicalRequestSource


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "custom_components" / "poolos" / "grid_outage_delivery.py"
PACKAGE_NAME = "poolos_grid_outage_delivery_behavior_test"


def load_module() -> ModuleType:
    package = ModuleType(PACKAGE_NAME)
    package.__path__ = [str(MODULE_PATH.parent)]
    package.__package__ = PACKAGE_NAME
    sys.modules[PACKAGE_NAME] = package
    manual = ModuleType(f"{PACKAGE_NAME}.manual_intellicenter")
    manual.ManualIntelliCenterControl = object
    sys.modules[manual.__name__] = manual
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.grid_outage_delivery", MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class FakeManual:
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = field(
        default_factory=list
    )

    async def async_set_body_heat_source(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("body_heat_source", args, kwargs))

    async def async_set_body_active(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("body_active", args, kwargs))

    async def async_set_circuit_state(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("circuit_active", args, kwargs))

    async def async_set_pump_circuit_speed(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("pump_circuit_speed", args, kwargs))


@pytest.mark.parametrize(
    ("kind", "operation", "target", "value", "concept", "priority"),
    (
        (GridOutageReductionKind.SPA_SOURCE_OFF, "body_heat_source", "B1202", "00000", "spa.raw_heater_id", 1),
        (GridOutageReductionKind.POOL_SOURCE_OFF, "body_heat_source", "B1101", "00000", "pool.raw_heater_id", 2),
        (GridOutageReductionKind.POOL_LIGHT_OFF, "circuit_active", "C0002", False, "pool_light.active", 3),
        (GridOutageReductionKind.JETS_OFF, "circuit_active", "C0003", False, "jets.active", 4),
        (GridOutageReductionKind.SLIDE_OFF, "circuit_active", "C0004", False, "slide.active", 5),
        (GridOutageReductionKind.WATERFALL_OFF, "circuit_active", "FTR01", False, "waterfall.active", 6),
        (GridOutageReductionKind.SPA_BODY_OFF, "body_active", "B1202", False, "spa.active", 7),
        (
            GridOutageReductionKind.POOL_PUMP_REDUCTION,
            "pump_circuit_speed",
            "p0199",
            1500,
            "pool.pump_circuit.configured_speed_rpm",
            9,
        ),
    ),
)
def test_adapter_routes_only_exact_candidate_through_outage_context(
    kind: GridOutageReductionKind,
    operation: str,
    target: str,
    value: bool | int | str,
    concept: str,
    priority: int,
) -> None:
    module = load_module()
    candidate = GridOutageReductionCandidate(
        candidate_id="candidate",
        outage_epoch_id="outage",
        frame_identity="frame",
        kind=kind,
        operation=operation,
        target=target,
        requested_value=value,
        expected_concept=concept,
        expected_native_object_id=target,
        priority=priority,
        evidence_fingerprint="evidence",
    )
    authority = SimpleNamespace(
        candidate_id="candidate",
        operation=operation,
        target=target,
        requested_value=value,
    )
    context = SimpleNamespace(authority=authority)
    manual = FakeManual()
    asyncio.run(module.ManualIntelliCenterGridOutageDelivery(manual, context).deliver(candidate))
    assert len(manual.calls) == 1
    assert manual.calls[0][0] == operation
    assert manual.calls[0][1] == (target, value)
    assert manual.calls[0][2] == {
        "request_source": PhysicalRequestSource.GRID_OUTAGE_SAFETY,
        "grid_outage_context": context,
    }


def test_adapter_rejects_candidate_context_mismatch_before_manual_call() -> None:
    module = load_module()
    candidate = GridOutageReductionCandidate(
        "candidate",
        "outage",
        "frame",
        GridOutageReductionKind.POOL_SOURCE_OFF,
        "body_heat_source",
        "B1101",
        "00000",
        "pool.raw_heater_id",
        "B1101",
        2,
        "evidence",
    )
    manual = FakeManual()
    context = SimpleNamespace(
        authority=SimpleNamespace(
            candidate_id="different",
            operation="body_heat_source",
            target="B1101",
            requested_value="00000",
        )
    )
    with pytest.raises(ValueError, match="does not match authorization"):
        asyncio.run(
            module.ManualIntelliCenterGridOutageDelivery(manual, context).deliver(
                candidate
            )
        )
    assert manual.calls == []
