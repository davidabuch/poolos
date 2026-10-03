"""Regression for live v0.11.0 Pool temperature-probe binding failure."""

from types import SimpleNamespace

from poolos.integration import (
    PhysicalHeatMode,
    SetBodyActive,
    SetHeatMode,
    SetPumpSpeed,
)
from poolos.physical_command_authority import (
    AutomaticThermalProbeAuthority,
    PoolOSPhysicalCommandAuthority,
)
from poolos.thermal_execution_currentness import ThermalExecutionPurposeKind


def test_pool_temperature_probe_authority_admits_exact_1500_rpm_step() -> None:
    """The canonical Pool probe must be able to own its exact 1500-RPM step."""

    authority = AutomaticThermalProbeAuthority(
        generation=1,
        epoch_identity="live-regression-epoch",
        operation_id="probe-rpm-step",
        operation="pump_circuit_speed",
        target="p0101",
        requested_value=1500,
    )

    assert authority.operation == "pump_circuit_speed"
    assert authority.target == "p0101"
    assert authority.requested_value == 1500


def test_pool_temperature_probe_authority_admits_exact_gpm_step() -> None:
    """A commissioned probe may bind an exact flow-domain pump step."""

    authority = AutomaticThermalProbeAuthority(
        generation=1,
        epoch_identity="live-gpm-probe-epoch",
        operation_id="probe-gpm-step",
        operation="pump_circuit_flow",
        target="p0101",
        requested_value=24,
    )

    assert authority.operation == "pump_circuit_flow"
    assert authority.target == "p0101"
    assert authority.requested_value == 24


def _production_factory_module():
    """Load the real HA automatic-runtime module with only HA dependencies stubbed."""
    import importlib.util
    from pathlib import Path
    import sys
    from types import ModuleType

    root = Path(__file__).resolve().parents[1]
    module_path = root / "custom_components" / "poolos" / "thermal_automatic_runtime.py"
    package_name = "poolos_v0111_probe_factory_regression"

    homeassistant = ModuleType("homeassistant")
    core = ModuleType("homeassistant.core")
    core.HomeAssistant = object
    homeassistant.core = core
    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.core"] = core

    package = ModuleType(package_name)
    package.__path__ = [str(module_path.parent)]
    package.__package__ = package_name
    sys.modules[package_name] = package

    for name, symbol in (
        ("coordinator", "PoolOSCoordinator"),
        ("manual_intellicenter", "ManualIntelliCenterControl"),
        ("observation", "ObservationSnapshot"),
        ("thermal_runtime", "PoolOSThermalRuntime"),
    ):
        stub = ModuleType(f"{package_name}.{name}")
        setattr(stub, symbol, object)
        sys.modules[stub.__name__] = stub

    delivery = ModuleType(f"{package_name}.thermal_live_delivery")

    class DummyDelivery:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    delivery.ManualIntelliCenterThermalLiveDelivery = DummyDelivery
    sys.modules[delivery.__name__] = delivery

    spec = importlib.util.spec_from_file_location(
        f"{package_name}.thermal_automatic_runtime",
        module_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _authority_ready_for_probe() -> PoolOSPhysicalCommandAuthority:
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    authority.set_controller_mode("auto")
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="pool",
    )
    return authority


def _probe_session(operation):
    """Minimal authentic session surface consumed by _ManualDeliveryFactory."""
    return SimpleNamespace(
        assessment=SimpleNamespace(
            operations=(operation,),
            desired=SimpleNamespace(body=SimpleNamespace(value="pool")),
        ),
        execution_plan=SimpleNamespace(
            plan_id="probe-plan",
            steps=(SimpleNamespace(operation=operation),),
        ),
        coordination=SimpleNamespace(current_step_sequence=1),
        originating_currentness=SimpleNamespace(
            purpose=SimpleNamespace(
                kind=ThermalExecutionPurposeKind.POOL_TEMPERATURE_PROBE
            )
        ),
    )


def test_real_ha_factory_binds_all_three_canonical_pool_probe_operations() -> None:
    module = _production_factory_module()
    authority = _authority_ready_for_probe()

    operations = (
        SetHeatMode(
            operation_id="probe-source-off",
            equipment_id="pool",
            mode=PhysicalHeatMode.OFF,
        ),
        SetBodyActive(
            operation_id="probe-pool-on",
            equipment_id="pool",
            active=True,
        ),
        SetPumpSpeed(
            operation_id="probe-rpm-1500",
            equipment_id="p0101",
            rpm=1500,
        ),
    )

    for index, operation in enumerate(operations, start=1):
        epoch = f"probe-epoch-{index}"
        authority.begin_automatic_thermal_epoch(epoch)

        factory = module._ManualDeliveryFactory(
            manual=object(),
            authority=authority,
        )

        delivery = factory.for_session(
            _probe_session(operation),
            epoch_identity=epoch,
        )

        context = delivery.kwargs["automatic_thermal_context"]

        assert context.purpose.value == "pool_temperature_probe"
        assert context.probe_authority is not None
        assert context.probe_authority.operation_id == operation.operation_id



def _external_spa_session(operation):
    """Minimal external-user Spa session consumed by the production factory."""

    return SimpleNamespace(
        assessment=SimpleNamespace(
            operations=(operation,),
            desired=SimpleNamespace(body=SimpleNamespace(value="hot_tub")),
        ),
        execution_plan=SimpleNamespace(
            plan_id="external-spa-plan",
            steps=(SimpleNamespace(operation=operation),),
        ),
        coordination=SimpleNamespace(current_step_sequence=1),
        originating_currentness=SimpleNamespace(
            purpose=SimpleNamespace(
                kind=ThermalExecutionPurposeKind.THERMAL_CONTROL
            )
        ),
    )


def test_real_ha_factory_context_passes_real_spa_pump_validator() -> None:
    """The exact factory context for ordinary Spa circulation must admit 2600 RPM."""

    from custom_components.poolos.thermal_live_delivery import (
        ManualIntelliCenterThermalLiveDelivery,
    )
    from poolos.physical_command_authority import PhysicalRequestSource

    module = _production_factory_module()
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    authority.set_controller_mode("auto")
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="both",
    )
    authority.begin_automatic_thermal_epoch("spa-validator-epoch")

    policy = module.ThermalLiveExecutionPolicy(
        pump_session_id="spa-session-1",
        pump_session_body="hot_tub",
        pump_session_purpose="ordinary_circulation",
        pump_session_pump_circuit_id="p0101",
        pump_session_effective_rpm=2600,
    )
    authority.synchronize_pump_speed_session(
        session_id="spa-session-1",
        body="hot_tub",
        purpose="ordinary_circulation",
        pump_circuit_id="p0101",
        effective_rpm=2600,
    )
    operation = SetPumpSpeed(
        operation_id="spa-normalize-validator",
        equipment_id="p0101",
        rpm=2600,
        metadata={"operating_purpose": "ordinary_circulation"},
    )
    factory = module._ManualDeliveryFactory(
        manual=object(),
        authority=authority,
        live_policy=policy,
    )
    delivery_stub = factory.for_session(
        _external_spa_session(operation),
        epoch_identity="spa-validator-epoch",
    )
    context = delivery_stub.kwargs["automatic_thermal_context"]

    real_delivery = ManualIntelliCenterThermalLiveDelivery(
        manual=object(),
        request_source=PhysicalRequestSource.AUTOMATIC_THERMAL,
        automatic_thermal_context=context,
    )
    real_delivery._validate_pump(operation)


def test_real_ha_factory_uses_frozen_frame_pump_session_for_spa_delivery() -> None:
    """A later pump-session publication cannot rewrite an older frame's command context."""

    module = _production_factory_module()
    authority = PoolOSPhysicalCommandAuthority()
    authority.resolve_maintenance(False)
    authority.set_controller_mode("auto")
    authority.configure_automatic_thermal(
        driver_enabled=True,
        thermal_live_enabled=True,
        commissioning_scope="both",
    )
    authority.begin_automatic_thermal_epoch("spa-epoch")

    policy = module.ThermalLiveExecutionPolicy(
        pump_session_id="spa-session-1",
        pump_session_body="hot_tub",
        pump_session_purpose="ordinary_circulation",
        pump_session_pump_circuit_id="p0101",
        pump_session_effective_rpm=2600,
    )
    authority.synchronize_pump_speed_session(
        session_id="spa-session-1",
        body="hot_tub",
        purpose="ordinary_circulation",
        pump_circuit_id="p0101",
        effective_rpm=2600,
    )
    operation = SetPumpSpeed(
        operation_id="spa-normalize",
        equipment_id="p0101",
        rpm=2600,
        metadata={"operating_purpose": "ordinary_circulation"},
    )
    factory = module._ManualDeliveryFactory(
        manual=object(),
        authority=authority,
        live_policy=policy,
    )

    delivery = factory.for_session(
        _external_spa_session(operation),
        epoch_identity="spa-epoch",
    )
    context = delivery.kwargs["automatic_thermal_context"]

    assert context.pump_session_id == "spa-session-1"
    assert context.effective_pump_rpm == 2600
    assert context.operating_purpose == "ordinary_circulation"
    assert context.pump_circuit_id == "p0101"
