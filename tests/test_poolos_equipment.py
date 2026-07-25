from poolos.equipment import Equipment
from poolos.enums import EquipmentType

def test_equipment():
    e=Equipment(id="pump",name="Pump",equipment_type=EquipmentType.PUMP)
    assert e.id=="pump"
