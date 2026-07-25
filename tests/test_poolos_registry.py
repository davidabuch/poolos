from poolos.registry import EquipmentRegistry
from poolos.equipment import Equipment
from poolos.enums import EquipmentType

def test_registry():
    r=EquipmentRegistry()
    e=Equipment(id="1",name="Pump",equipment_type=EquipmentType.PUMP)
    r.register(e)
    assert r.get("1") is e
    assert len(r.all())==1
