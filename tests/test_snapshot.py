from dataclasses import FrozenInstanceError

import pytest


def test_refresh_replaces_snapshot_and_supports_lookup(
    api_modules,
    pool_object_factory,
    heater_object_factory,
    coordinator_factory,
):
    pool = pool_object_factory("B1101", name="Pool", subtype="POOL")
    spa = pool_object_factory("B1102", name="Spa", subtype="SPA")
    heater = heater_object_factory()
    coordinator = coordinator_factory([pool, spa, heater])
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
