from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest

from poolos.hal import CommandStatus
from poolos.integration import (
    PhysicalHeatMode,
    SetBodyActive,
    SetHeatMode,
    SetPumpSpeed,
    StartPump,
    ThermalBody,
)


@dataclass(frozen=True)
class ManualCommandReceipt:
    body_objnam: str
    operation: str
    value: bool | int | str


class ManualIntelliCenterCommandError(RuntimeError):
    pass


def _load_adapter_class():
    package_name = "_poolos_thermal_live_delivery_test"
    module_name = f"{package_name}.thermal_live_delivery"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing.ManualIntelliCenterThermalLiveDelivery

    package = ModuleType(package_name)
    package.__path__ = []
    manual = ModuleType(f"{package_name}.manual_intellicenter")
    manual.ManualCommandReceipt = ManualCommandReceipt
    manual.ManualIntelliCenterCommandError = ManualIntelliCenterCommandError
    manual.ManualIntelliCenterControl = object
    sys.modules[package_name] = package
    sys.modules[manual.__name__] = manual

    path = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "poolos"
        / "thermal_live_delivery.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.ManualIntelliCenterThermalLiveDelivery


ManualIntelliCenterThermalLiveDelivery = _load_adapter_class()


@dataclass
class FakeManualControl:
    available: bool = True
    calls: list[tuple[str, object, object]] = field(default_factory=list)

    async def async_set_body_active(
        self,
        target: str,
        active: bool,
        **kwargs: object,
    ) -> ManualCommandReceipt:
        del kwargs
        self.calls.append(("body", target, active))
        return ManualCommandReceipt(target, "body_active", active)

    async def async_set_pump_circuit_speed(
        self,
        target: str,
        rpm: int,
        **kwargs: object,
    ) -> ManualCommandReceipt:
        del kwargs
        self.calls.append(("pump", target, rpm))
        return ManualCommandReceipt(target, "pump_circuit_speed", rpm)

    async def async_set_body_heat_source(
        self,
        target: str,
        heater_id: str,
        **kwargs: object,
    ) -> ManualCommandReceipt:
        del kwargs
        self.calls.append(("heater", target, heater_id))
        return ManualCommandReceipt(target, "body_heat_source", heater_id)


def adapter(manual: FakeManualControl):
    return ManualIntelliCenterThermalLiveDelivery(manual=manual)


def test_adapter_reuses_manual_gateway_for_commissioned_thermal_operations() -> None:
    manual = FakeManualControl()
    delivery = adapter(manual)

    pump = asyncio.run(
        delivery.deliver(
            SetPumpSpeed(equipment_id="p0102", rpm=2900),
            correlation_id="pump-step",
        )
    )
    heater = asyncio.run(
        delivery.deliver(
            SetHeatMode(
                equipment_id=ThermalBody.HOT_TUB,
                mode=PhysicalHeatMode.GAS,
            ),
            correlation_id="heater-step",
        )
    )

    assert manual.calls == [
        ("pump", "p0102", 2900),
        ("heater", "B1202", "H0001"),
    ]
    assert pump.status is CommandStatus.ACKNOWLEDGED
    assert heater.status is CommandStatus.ACKNOWLEDGED
    assert pump.verification_required and heater.verification_required


def test_adapter_rejects_nonthermal_or_uncommissioned_operations_before_manual_call() -> None:
    manual = FakeManualControl()
    delivery = adapter(manual)

    filtration = asyncio.run(
        delivery.deliver(
            SetPumpSpeed(equipment_id="p0102", rpm=2600),
            correlation_id="filtration",
        )
    )
    unknown_pump = asyncio.run(
        delivery.deliver(
            SetPumpSpeed(equipment_id="other", rpm=2900),
            correlation_id="other-pump",
        )
    )
    start = asyncio.run(
        delivery.deliver(
            StartPump(equipment_id="p0102"),
            correlation_id="start",
        )
    )

    assert manual.calls == []
    assert {filtration.status, unknown_pump.status, start.status} == {
        CommandStatus.REJECTED
    }


@pytest.mark.parametrize(
    ("body", "mode", "native_body", "native_heater"),
    (
        (ThermalBody.POOL, PhysicalHeatMode.OFF, "B1101", "00000"),
        (ThermalBody.POOL, PhysicalHeatMode.GAS, "B1101", "H0001"),
        (ThermalBody.POOL, PhysicalHeatMode.SOLAR, "B1101", "H0002"),
        (ThermalBody.HOT_TUB, PhysicalHeatMode.OFF, "B1202", "00000"),
        (ThermalBody.HOT_TUB, PhysicalHeatMode.GAS, "B1202", "H0001"),
        (ThermalBody.HOT_TUB, PhysicalHeatMode.SOLAR, "B1202", "H0002"),
    ),
)
def test_adapter_explicitly_maps_only_commissioned_body_and_heat_mode(
    body: ThermalBody,
    mode: PhysicalHeatMode,
    native_body: str,
    native_heater: str,
) -> None:
    manual = FakeManualControl()
    delivery = adapter(manual)

    receipt = asyncio.run(
        delivery.deliver(
            SetHeatMode(equipment_id=body, mode=mode),
            correlation_id=f"{body.value}-{mode.value}",
        )
    )

    assert receipt.status is CommandStatus.ACKNOWLEDGED
    assert manual.calls == [("heater", native_body, native_heater)]


@pytest.mark.parametrize("invalid_field", ("body", "mode"))
def test_adapter_rejects_forged_heat_mode_without_manual_call(
    invalid_field: str,
) -> None:
    operation = SetHeatMode(
        equipment_id=ThermalBody.POOL,
        mode=PhysicalHeatMode.SOLAR,
    )
    if invalid_field == "body":
        object.__setattr__(operation, "equipment_id", "spillway")
    else:
        object.__setattr__(operation, "mode", "solar_preferred")
    manual = FakeManualControl()

    receipt = asyncio.run(
        adapter(manual).deliver(operation, correlation_id="forged-heat-mode")
    )

    assert receipt.status is CommandStatus.REJECTED
    assert receipt.details["error_type"] == "ValueError"
    assert manual.calls == []


def test_adapter_availability_is_read_only_and_does_not_start_manual_control() -> None:
    manual = FakeManualControl(available=False)
    delivery = adapter(manual)

    assert delivery.available is False
    assert manual.calls == []


@pytest.mark.parametrize(
    ("body", "native_body"),
    (
        (ThermalBody.POOL, "B1101"),
        (ThermalBody.HOT_TUB, "B1202"),
    ),
)
def test_adapter_delivers_only_commissioned_body_activation(
    body: ThermalBody,
    native_body: str,
) -> None:
    manual = FakeManualControl()

    receipt = asyncio.run(
        adapter(manual).deliver(
            SetBodyActive(
                equipment_id=body,
                active=True,
            ),
            correlation_id=f"activate-{body.value}",
        )
    )

    assert receipt.status is CommandStatus.ACKNOWLEDGED
    assert receipt.verification_required is True
    assert manual.calls == [("body", native_body, True)]


def test_adapter_rejects_autonomous_body_deactivation_before_manual_call() -> None:
    manual = FakeManualControl()

    receipt = asyncio.run(
        adapter(manual).deliver(
            SetBodyActive(
                equipment_id=ThermalBody.POOL,
                active=False,
            ),
            correlation_id="body-off",
        )
    )

    assert receipt.status is CommandStatus.REJECTED
    assert receipt.details["error_type"] == "ValueError"
    assert manual.calls == []


def test_adapter_accepts_explicit_priming_rpm_baseline() -> None:
    manual = FakeManualControl()

    receipt = asyncio.run(
        adapter(manual).deliver(
            SetPumpSpeed(
                equipment_id="p0102",
                rpm=3000,
                metadata={"reason_code": "cold_start_pump_priming"},
            ),
            correlation_id="prime",
        )
    )

    assert receipt.status is CommandStatus.ACKNOWLEDGED
    assert manual.calls == [("pump", "p0102", 3000)]
