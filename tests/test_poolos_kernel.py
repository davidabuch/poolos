from poolos.capabilities import Capability
from poolos.equipment import Equipment
from poolos.enums import EquipmentType
from poolos.kernel import PoolKernel

def test_kernel_registry():
    k = PoolKernel()
    pump = Equipment(
        id="pump",
        name="Pump",
        equipment_type=EquipmentType.PUMP,
        capabilities=frozenset({Capability.CIRCULATION.value}),
    )
    k.equipment.register(pump)
    assert len(k.equipment.find_by_type(EquipmentType.PUMP)) == 1
    assert len(k.equipment.find_by_capability(Capability.CIRCULATION)) == 1
