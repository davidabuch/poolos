from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from poolos.capabilities import Capability
from poolos.hal import (
    AdapterHealth,
    AdapterHealthState,
    AdapterMetadata,
    AdapterRegistry,
    CommandReceipt,
    CommandStatus,
    DuplicateAdapterError,
    EquipmentMetadata,
    EquipmentObservation,
    HardwareAdapter,
    HomeAssistantTransport,
    Pump,
    RS485Transport,
    SimulatorTransport,
    TransportState,
    TransportUnavailableError,
    UnsupportedCapabilityError,
)


class FakePump(Pump):
    def __init__(self, adapter_id="fake", caps=None):
        self._rpm = 0
        self._metadata = EquipmentMetadata(
            equipment_id="pump-1",
            name="Main Pump",
            equipment_type="pump",
            adapter_id=adapter_id,
            capabilities=frozenset(caps or {Capability.START_STOP, Capability.RPM_CONTROL, Capability.RPM_SENSING}),
        )

    @property
    def metadata(self):
        return self._metadata

    def observe(self):
        return EquipmentObservation(self.metadata.equipment_id, {"rpm": self._rpm})

    def faults(self):
        return ()

    def start(self):
        return CommandReceipt(CommandStatus.ACCEPTED)

    def stop(self):
        self._rpm = 0
        return CommandReceipt(CommandStatus.ACCEPTED)

    def _set_speed_rpm(self, rpm):
        self._rpm = rpm
        return CommandReceipt(CommandStatus.SENT)

    def actual_rpm(self):
        return self._rpm

    def power_watts(self):
        return None


class FakeAdapter(HardwareAdapter):
    def __init__(self, adapter_id="fake", transport=None):
        super().__init__(transport or SimulatorTransport())
        self._metadata = AdapterMetadata(adapter_id, "Fake Adapter", "1.0", supported_equipment=("pump",))
        self._health = AdapterHealth()
        self.pump = FakePump(adapter_id)

    @property
    def metadata(self):
        return self._metadata

    def initialize(self):
        self._health = AdapterHealth(AdapterHealthState.INITIALIZING)

    def connect(self):
        self.transport.connect()
        self._health = AdapterHealth(AdapterHealthState.CONNECTED, last_contact=datetime.now(timezone.utc))

    def disconnect(self):
        self.transport.disconnect()
        self._health = AdapterHealth(AdapterHealthState.DISCONNECTED)

    def discover(self):
        return (self.pump,)

    def health(self):
        return self._health


def test_simulator_transport_round_trip_and_metadata():
    transport = SimulatorTransport()
    transport.connect()
    response = transport.send("pump/1", {"rpm": 2400})
    assert response.accepted and response.acknowledged
    assert transport.read("pump/1").payload == {"rpm": 2400}
    assert transport.metadata().state is TransportState.CONNECTED


def test_simulator_requires_connection():
    with pytest.raises(TransportUnavailableError):
        SimulatorTransport().read("anything")


def test_optional_capability_is_checked_before_command():
    pump = FakePump(caps={Capability.START_STOP})
    with pytest.raises(UnsupportedCapabilityError):
        pump.set_speed_rpm(1800)


def test_supported_pump_command_returns_receipt_and_observation():
    pump = FakePump()
    receipt = pump.set_speed_rpm(2200)
    assert receipt.status is CommandStatus.SENT
    assert receipt.verification_required
    assert pump.observe().values["rpm"] == 2200


def test_adapter_registry_discovery_and_hot_replacement():
    registry = AdapterRegistry()
    first = FakeAdapter("pentair")
    registry.register(first)
    assert registry.get("pentair") is first
    assert registry.discover_all()[0].metadata.equipment_id == "pump-1"

    second = FakeAdapter("pentair")
    registry.replace(second)
    assert registry.get("pentair") is second


def test_duplicate_adapter_registration_is_rejected():
    registry = AdapterRegistry()
    registry.register(FakeAdapter("same"))
    with pytest.raises(DuplicateAdapterError):
        registry.register(FakeAdapter("same"))


def test_adapter_lifecycle_and_health():
    adapter = FakeAdapter()
    adapter.initialize()
    assert adapter.health().state is AdapterHealthState.INITIALIZING
    adapter.connect()
    assert adapter.health().writable
    adapter.shutdown()
    assert adapter.health().state is AdapterHealthState.DISCONNECTED


def test_future_transports_are_explicit_unavailable_stubs():
    with pytest.raises(TransportUnavailableError):
        HomeAssistantTransport().connect()
    with pytest.raises(TransportUnavailableError):
        RS485Transport().connect()
