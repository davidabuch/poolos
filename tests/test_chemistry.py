from dataclasses import FrozenInstanceError

import pytest


def test_builds_intellichem_with_measurements_settings_and_alarms(
    api_modules,
    pool_object_factory,
    chemistry_object_factory,
    coordinator_factory,
):
    pool = pool_object_factory("B1101", name="Pool")
    chemistry = chemistry_object_factory()

    api = api_modules.system.IntelliCenterAPI(
        coordinator_factory([pool, chemistry])
    )
    state = api.refresh().chemistries[0]

    assert state is api.chemistry("CH0001")
    assert state.name == "IntelliChem"
    assert state.chemistry_type is api_modules.models.ChemistryType.INTELLICHEM
    assert state.subtype == "ICHEM"
    assert state.body_ids == ("B1101",)
    assert state.body_names == ("Pool",)
    assert state.ph == 7.4
    assert state.orp_mv == 675.0
    assert state.water_quality == 95.0
    assert state.ph_setpoint == 7.3
    assert state.orp_setpoint_mv == 700
    assert state.alkalinity_ppm == 90
    assert state.calcium_hardness_ppm == 350
    assert state.cyanuric_acid_ppm == 40
    assert state.ph_tank_level == 5
    assert state.orp_tank_level == 3
    assert state.ph_dosing_volume_ml == 1250.0
    assert state.orp_dosing_volume_ml == 850.0
    assert state.ph_high_alarm is False
    assert state.ph_low_alarm is True
    assert state.orp_high_alarm is False
    assert state.orp_low_alarm is True
    assert state.salt_ppm is None
    assert state.primary_output_percent is None
    assert state.secondary_output_percent is None
    assert state.superchlorinate is False


def test_builds_intellichlor_with_two_body_relationships(
    api_modules,
    pool_object_factory,
    chemistry_object_factory,
    coordinator_factory,
):
    pool = pool_object_factory("B1101", name="Pool")
    spa = pool_object_factory("B1102", name="Spa")
    chlorinator = chemistry_object_factory(
        "CH0002",
        name="IntelliChlor",
        subtype="ICHLOR",
        body_ids="B1101 B1102",
        ph=None,
        orp=None,
        quality=None,
        ph_setpoint=None,
        orp_setpoint=None,
        alkalinity=None,
        calcium=None,
        cyanuric_acid=None,
        ph_tank=None,
        orp_tank=None,
        ph_volume=None,
        orp_volume=None,
        salt="3250",
        primary_output="55",
        secondary_output=20.9,
        superchlorinate="enabled",
    )

    state = api_modules.system.IntelliCenterAPI(
        coordinator_factory([pool, spa, chlorinator])
    ).refresh().chemistries[0]

    assert state.chemistry_type is api_modules.models.ChemistryType.INTELLICHLOR
    assert state.body_ids == ("B1101", "B1102")
    assert state.body_names == ("Pool", "Spa")
    assert state.salt_ppm == 3250
    assert state.primary_output_percent == 55
    assert state.secondary_output_percent == 20
    assert state.superchlorinate is True


def test_unknown_body_ids_are_preserved_and_missing_relationship_is_empty(
    api_modules,
    chemistry_object_factory,
    coordinator_factory,
):
    linked = chemistry_object_factory(body_ids="B9999")
    unlinked = chemistry_object_factory("CH0002", body_ids=None)

    snapshot = api_modules.system.IntelliCenterAPI(
        coordinator_factory([linked, unlinked])
    ).refresh()

    assert snapshot.chemistries[0].body_ids == ("B9999",)
    assert snapshot.chemistries[0].body_names == ("B9999",)
    assert snapshot.chemistries[1].body_ids == ()
    assert snapshot.chemistries[1].body_names == ()


def test_invalid_values_do_not_escape_and_text_quality_is_preserved(
    api_modules,
    chemistry_object_factory,
    coordinator_factory,
):
    chemistry = chemistry_object_factory(
        subtype="mystery",
        ph="bad",
        orp="",
        quality="CHECK FLOW",
        ph_setpoint=None,
        orp_setpoint="bad",
        alkalinity="bad",
        calcium=None,
        cyanuric_acid="",
        ph_tank="bad",
        orp_tank=None,
        ph_volume="bad",
        orp_volume="",
        ph_high="off",
        ph_low="no",
        orp_high=0,
        orp_low=None,
        salt="bad",
        primary_output="bad",
        secondary_output=None,
        superchlorinate="disabled",
    )

    state = api_modules.system.IntelliCenterAPI(
        coordinator_factory([chemistry])
    ).refresh().chemistries[0]

    assert state.chemistry_type is api_modules.models.ChemistryType.UNKNOWN
    assert state.ph is None
    assert state.orp_mv is None
    assert state.water_quality == "CHECK FLOW"
    assert state.orp_setpoint_mv is None
    assert state.alkalinity_ppm is None
    assert state.calcium_hardness_ppm is None
    assert state.cyanuric_acid_ppm is None
    assert state.ph_tank_level is None
    assert state.orp_tank_level is None
    assert state.ph_dosing_volume_ml is None
    assert state.orp_dosing_volume_ml is None
    assert state.ph_high_alarm is False
    assert state.ph_low_alarm is False
    assert state.orp_high_alarm is False
    assert state.orp_low_alarm is False
    assert state.salt_ppm is None
    assert state.primary_output_percent is None
    assert state.secondary_output_percent is None
    assert state.superchlorinate is False


def test_chemistry_lookup_and_snapshot_are_immutable(
    api_modules,
    chemistry_object_factory,
    coordinator_factory,
):
    chemistry = chemistry_object_factory()
    api = api_modules.system.IntelliCenterAPI(coordinator_factory([chemistry]))
    snapshot = api.refresh()

    assert api.chemistry("CH0001") is snapshot.chemistries[0]
    assert api.chemistry("missing") is None
    with pytest.raises(FrozenInstanceError):
        snapshot.chemistries[0].ph = 7.2
