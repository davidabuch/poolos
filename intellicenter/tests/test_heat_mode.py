from homeassistant.const import UnitOfTemperature


def build(api_modules, coordinator, body):
    return api_modules.body.build_body_state(
        coordinator,
        body,
        (),
        40.0,
        104.0,
        UnitOfTemperature.FAHRENHEIT,
    )


def test_heating_requested_is_distinct_from_heating_active(
    api_modules, pool_object_factory, coordinator_factory
):
    body = pool_object_factory(current=86, target=90)
    coordinator = coordinator_factory([body])

    requested_only = build(api_modules, coordinator, body)
    assert requested_only.heating_requested is True
    assert requested_only.heating_active is False

    coordinator.controller.heating.add(body.objnam)
    active = build(api_modules, coordinator, body)
    assert active.heating_requested is True
    assert active.heating_active is True


def test_cooling_body_reports_heat_cool_and_cooling_request(
    api_modules, pool_object_factory, coordinator_factory
):
    body = pool_object_factory(current=100, target=88, cooling_target=95)
    coordinator = coordinator_factory([body])
    coordinator.controller.cooling_supported.add(body.objnam)
    coordinator.controller.cooling.add(body.objnam)

    state = build(api_modules, coordinator, body)

    assert state.heat_mode is api_modules.models.HeatMode.HEAT_COOL
    assert state.cooling_requested is True
    assert state.cooling_active is True
