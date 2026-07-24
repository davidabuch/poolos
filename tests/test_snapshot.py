from dataclasses import FrozenInstanceError

import pytest


def test_refresh_replaces_snapshot_and_supports_lookup(
    api_modules,
    pool_object_factory,
    heater_object_factory,
    coordinator_factory,
    pump_object_factory,
    chemistry_object_factory,
    system_object_factory,
    cover_object_factory,
):
    pool = pool_object_factory("B1101", name="Pool", subtype="POOL")
    spa = pool_object_factory("B1102", name="Spa", subtype="SPA")
    heater = heater_object_factory()
    pump = pump_object_factory()
    chemistry = chemistry_object_factory()
    system = system_object_factory()
    cover = cover_object_factory()
    coordinator = coordinator_factory(
        [pool, spa, heater, pump, chemistry, system, cover]
    )
    coordinator.heaters_by_body = {
        pool.objnam: (heater.objnam,),
        spa.objnam: (heater.objnam,),
    }

    api = api_modules.system.IntelliCenterAPI(coordinator)
    original = api.snapshot
    refreshed = api.refresh()

    assert refreshed is not original
    assert api.pool is not None and api.pool.id == "B1101"
    assert api.spa is not None and api.spa.id == "B1102"
    assert api.body("B1102") is api.spa
    assert api.body("missing") is None
    assert api.pump("P0001") is api.pumps[0]
    assert api.pump("missing") is None
    assert api.chemistry("CH0001") is api.chemistries[0]
    assert api.chemistry("missing") is None
    assert api.cover("X0001") is api.covers[0]
    assert api.cover("missing") is None
    assert refreshed.covers == api.covers
    assert api.system is refreshed.system
    assert api.system is not None and api.system.id == "SYSTM"


def test_snapshot_is_immutable_and_tracks_connection_state(
    api_modules,
    pool_object_factory,
    heater_object_factory,
    coordinator_factory,
):
    body = pool_object_factory()
    heater = heater_object_factory()
    coordinator = coordinator_factory([body, heater], connected=False)
    coordinator.heaters_by_body[body.objnam] = (heater.objnam,)

    snapshot = api_modules.system.IntelliCenterAPI(coordinator).refresh()

    assert snapshot.connected is False
    with pytest.raises(FrozenInstanceError):
        snapshot.connected = True


def test_body_without_heater_remains_in_hardware_snapshot(
    api_modules, pool_object_factory, coordinator_factory
):
    body = pool_object_factory(current=82)
    coordinator = coordinator_factory([body])

    api = api_modules.system.IntelliCenterAPI(coordinator)
    snapshot = api.refresh()

    assert len(snapshot.bodies) == 1
    assert snapshot.bodies[0].id == body.objnam
    assert snapshot.bodies[0].current_temperature == 82
    assert snapshot.bodies[0].available_heaters == ()
