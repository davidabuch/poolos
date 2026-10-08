"""Exact delivery-envelope tests for autonomous Pool filtration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import importlib.util
from pathlib import Path
import sys
from types import ModuleType

from poolos.hal import CommandStatus
from poolos.integration import SetBodyActive, SetPumpFlow, SetPumpSpeed
from poolos.operating_baselines import PumpOperatingBaselines
from poolos.pump_operating_target import PumpOperatingTarget, PumpTargetUnit
from poolos.physical_command_authority import AutomaticFiltrationDispatchContext


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "custom_components" / "poolos" / "filtration_live_delivery.py"
PACKAGE_NAME = "poolos_filtration_delivery_behavior_test"


def _load_module() -> ModuleType:
    package = ModuleType(PACKAGE_NAME)
    package.__path__ = [str(MODULE_PATH.parent)]
    package.__package__ = PACKAGE_NAME
    sys.modules[PACKAGE_NAME] = package
    manual = ModuleType(f"{PACKAGE_NAME}.manual_intellicenter")

    class ManualIntelliCenterCommandError(RuntimeError):
        pass

    class ManualIntelliCenterCommandNotDispatchedError(ManualIntelliCenterCommandError):
        pass

    manual.ManualIntelliCenterCommandError = ManualIntelliCenterCommandError
    manual.ManualIntelliCenterCommandNotDispatchedError = (
        ManualIntelliCenterCommandNotDispatchedError
    )
    manual.ManualIntelliCenterControl = object
    sys.modules[manual.__name__] = manual
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.filtration_live_delivery",
        MODULE_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _context(*, operation: str, target: str, value: bool | int):
    return AutomaticFiltrationDispatchContext(
        generation=1,
        epoch_identity="epoch-1",
        session_identity="session-1",
        operation_identity="operation-1",
        operation=operation,
        target=target,
        requested_value=value,
        pump_circuit_id="p0102",
    )


@dataclass
class FakeManual:
    available: bool = True
    body_calls: list[tuple[object, ...]] = field(default_factory=list)
    pump_calls: list[tuple[object, ...]] = field(default_factory=list)

    async def async_set_body_active(self, *args: object, **kwargs: object) -> None:
        self.body_calls.append((*args, kwargs))

    async def async_set_pump_circuit_speed(
        self,
        *args: object,
        **kwargs: object,
    ) -> None:
        self.pump_calls.append((*args, kwargs))

    async def async__set_pump_circuit_flow(
        self,
        *args: object,
        **kwargs: object,
    ) -> None:
        self.pump_calls.append((*args, kwargs))


def test_exact_pool_body_and_dynamic_2600_commands_use_existing_manual_gateway() -> None:
    module = _load_module()
    manual = FakeManual()
    body = module.ManualIntelliCenterFiltrationDelivery(
        manual,
        _context(operation="body_active", target="B1101", value=True),
    )
    pump = module.ManualIntelliCenterFiltrationDelivery(
        manual,
        _context(operation="pump_circuit_speed", target="p0102", value=2600),
    )

    body_receipt = asyncio.run(
        body.deliver(SetBodyActive(equipment_id="pool", active=True), correlation_id="body")
    )
    pump_receipt = asyncio.run(
        pump.deliver(SetPumpSpeed(equipment_id="p0102", rpm=2600), correlation_id="pump")
    )

    assert body_receipt.status is CommandStatus.ACKNOWLEDGED
    assert pump_receipt.status is CommandStatus.ACKNOWLEDGED
    assert manual.body_calls[0][0:2] == ("B1101", True)
    assert manual.pump_calls[0][0:2] == ("p0102", 2600)


def test_wrong_body_pump_identity_or_rpm_is_rejected_before_manual_delivery() -> None:
    module = _load_module()
    manual = FakeManual()
    body = module.ManualIntelliCenterFiltrationDelivery(
        manual,
        _context(operation="body_active", target="B1101", value=True),
    )
    pump = module.ManualIntelliCenterFiltrationDelivery(
        manual,
        _context(operation="pump_circuit_speed", target="p0102", value=2600),
    )

    receipts = (
        asyncio.run(
            body.deliver(
                SetBodyActive(equipment_id="hot_tub", active=True),
                correlation_id="spa",
            )
        ),
        asyncio.run(
            pump.deliver(
                SetPumpSpeed(equipment_id="p0103", rpm=2600),
                correlation_id="wrong-pump",
            )
        ),
        asyncio.run(
            pump.deliver(
                SetPumpSpeed(equipment_id="p0102", rpm=1500),
                correlation_id="wrong-rpm",
            )
        ),
    )

    assert all(receipt.status is CommandStatus.REJECTED for receipt in receipts)
    assert manual.body_calls == []
    assert manual.pump_calls == []


def test_non_default_filtration_rpm_reaches_manual_gateway_exactly() -> None:
    module = _load_module()
    manual = FakeManual()
    baselines = PumpOperatingBaselines(filtration_rpm=2650)
    delivery = module.ManualIntelliCenterFiltrationDelivery(
        manual,
        _context(operation="pump_circuit_speed", target="p0102", value=2650),
        baselines,
    )

    configured = asyncio.run(
        delivery.deliver(
            SetPumpSpeed(equipment_id="p0102", rpm=2650),
            correlation_id="configured",
        )
    )
    old_default = asyncio.run(
        delivery.deliver(
            SetPumpSpeed(equipment_id="p0102", rpm=2600),
            correlation_id="old-default",
        )
    )

    assert configured.status is CommandStatus.ACKNOWLEDGED
    assert old_default.status is CommandStatus.REJECTED
    assert manual.pump_calls[0][0:2] == ("p0102", 2650)



def test_exact_gpm_filtration_target_reaches_private_flow_gateway() -> None:
    module = _load_module()
    manual = FakeManual()
    target = PumpOperatingTarget(PumpTargetUnit.GPM, 42)
    context = AutomaticFiltrationDispatchContext(
        generation=1,
        epoch_identity="epoch-gpm",
        session_identity="session-gpm",
        operation_identity="operation-gpm",
        operation="pump_circuit_flow",
        target="p0102",
        requested_value=42,
        pump_circuit_id="p0102",
        pump_session_id="pump-target-session",
        effective_pump_target=target,
    )
    delivery = module.ManualIntelliCenterFiltrationDelivery(manual, context)

    receipt = asyncio.run(
        delivery.deliver(
            SetPumpFlow(equipment_id="p0102", gpm=42),
            correlation_id="gpm",
        )
    )

    assert receipt.status is CommandStatus.ACKNOWLEDGED
    assert manual.pump_calls[0][0:2] == ("p0102", 42)
    assert manual.pump_calls[0][-1]["request_source"].value == "automatic_filtration"
    assert manual.pump_calls[0][-1]["automatic_filtration_context"] == context


def test_gpm_filtration_delivery_rejects_wrong_flow_before_gateway() -> None:
    module = _load_module()
    manual = FakeManual()
    context = AutomaticFiltrationDispatchContext(
        generation=1,
        epoch_identity="epoch-gpm",
        session_identity="session-gpm",
        operation_identity="operation-gpm",
        operation="pump_circuit_flow",
        target="p0102",
        requested_value=42,
        pump_circuit_id="p0102",
        pump_session_id="pump-target-session",
        effective_pump_target=PumpOperatingTarget(PumpTargetUnit.GPM, 42),
    )
    delivery = module.ManualIntelliCenterFiltrationDelivery(manual, context)

    receipt = asyncio.run(
        delivery.deliver(
            SetPumpFlow(equipment_id="p0102", gpm=50),
            correlation_id="wrong-gpm",
        )
    )

    assert receipt.status is CommandStatus.REJECTED
    assert manual.pump_calls == []


def test_gateway_not_dispatched_cleanup_denial_does_not_poison_body() -> None:
    module = _load_module()

    class RejectedManual(FakeManual):
        async def async_set_body_active(self, *args: object, **kwargs: object) -> None:
            raise module.ManualIntelliCenterCommandNotDispatchedError(
                "authority changed before transport"
            )

    manual = RejectedManual()
    delivery = module.ManualIntelliCenterFiltrationDelivery(
        manual, AutomaticFiltrationDispatchContext(
            generation=1, epoch_identity="epoch-1", session_identity="session-1",
            operation_identity="operation-1", operation="body_active",
            target="B1101", requested_value=False, pump_circuit_id="p0102",
            ownership_lease_id="lease-1", body_activation_receipt_id="receipt-1",
            purpose="owned_body_cleanup",
        ),
    )
    receipt = asyncio.run(delivery.deliver(
        SetBodyActive(equipment_id="pool", active=False),
        correlation_id="denied-cleanup",
    ))
    assert receipt.status is CommandStatus.REJECTED
    assert receipt.details["definitely_not_dispatched"] is True
    assert not receipt.accepted
