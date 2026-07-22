from homeassistant.const import UnitOfTemperature


def _build(api_modules, coordinator, body):
    return api_modules.body.build_body_state(
        coordinator,
        body,
        coordinator.heaters_by_body.get(body.objnam, ()),
        40.0,
        104.0,
        UnitOfTemperature.FAHRENHEIT,
    )


def test_pool_and_spa_type_detection(
    api_modules, pool_object_factory, coordinator_factory
):
    pool = pool_object_factory(name="Main Pool", subtype="POOL")
    spa = pool_object_factory("B1102", name="Family Spa", subtype="SPA")
    coordinator = coordinator_factory([pool, spa])

    assert _build(api_modules, coordinator, pool).body_type is api_modules.models.BodyType.POOL
    assert _build(api_modules, coordinator, spa).body_type is api_modules.models.BodyType.SPA


def test_body_off_normalizes_heat_mode_and_requests(
    api_modules, pool_object_factory, coordinator_factory
):
    body = pool_object_factory(status="OFF", current=80, target=100)
    coordinator = coordinator_factory([body])

    state = _build(api_modules, coordinator, body)

    assert state.is_on is False
    assert state.heat_mode is api_modules.models.HeatMode.OFF
    assert state.heating_requested is False
    assert state.heating_active is False
