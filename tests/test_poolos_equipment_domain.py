from poolos.capabilities import Capability
from poolos.enums import EquipmentType
from poolos.equipment import Equipment, FilterEquipment


def test_equipment_can_be_shared_between_pool_and_spa():
    pump = Equipment(
        id="main_pump",
        name="Main VS Pump",
        equipment_type=EquipmentType.PUMP,
        capabilities=frozenset({Capability.START_STOP, Capability.RPM_CONTROL}),
        system_id="main",
        shared_body_ids=frozenset({"pool", "spa"}),
    )

    assert pump.shared_body_ids == frozenset({"pool", "spa"})
    assert pump.has_capability(Capability.RPM_CONTROL)


def test_filter_does_not_claim_pressure_when_only_analog_gauge_exists():
    equipment = Equipment(
        id="filter",
        name="Cartridge Filter",
        equipment_type=EquipmentType.FILTER,
        capabilities=frozenset({Capability.FILTERING, Capability.MAINTENANCE_TRACKING}),
    )
    filter_model = FilterEquipment(
        equipment=equipment,
        media_type="cartridge",
        filter_area_sq_ft=520,
        pressure_psi=None,
        estimated_health=0.84,
    )

    assert filter_model.has_digital_pressure is False
    assert filter_model.estimated_health == 0.84
