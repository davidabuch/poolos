from homeassistant.const import UnitOfTemperature


def test_invalid_temperature_values_are_contained(
    api_modules, pool_object_factory, coordinator_factory
):
    body = pool_object_factory(current="not-a-number", target=None, cooling_target="")
    coordinator = coordinator_factory([body])

    state = api_modules.body.build_body_state(
        coordinator,
        body,
        (),
        40.0,
        104.0,
        UnitOfTemperature.FAHRENHEIT,
    )

    assert state.current_temperature is None
    assert state.target_temperature is None
    assert state.cooling_target_temperature is None
    assert state.heating_requested is False


def test_metric_snapshot_uses_celsius_limits(
    api_modules, pool_object_factory, coordinator_factory
):
    body = pool_object_factory(current=30, target=32)
    coordinator = coordinator_factory([body], metric=True)
    coordinator.heaters_by_body[body.objnam] = ("H0001",)

    snapshot = api_modules.system.IntelliCenterAPI(coordinator).refresh()
    state = snapshot.bodies[0]

    assert snapshot.temperature_unit is UnitOfTemperature.CELSIUS
    assert state.min_temperature == 5.0
    assert state.max_temperature == 40.0
