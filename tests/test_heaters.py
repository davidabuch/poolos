from homeassistant.const import UnitOfTemperature


def test_selected_heater_is_normalized_to_heat_source(
    api_modules,
    pool_object_factory,
    heater_object_factory,
    coordinator_factory,
):
    body = pool_object_factory(heater="H0001")
    heater = heater_object_factory(name="Pentair MasterTemp", subtype="GAS")
    coordinator = coordinator_factory([body, heater])
    coordinator.heaters_by_body[body.objnam] = (heater.objnam,)

    state = api_modules.body.build_body_state(
        coordinator,
        body,
        coordinator.heaters_by_body[body.objnam],
        40.0,
        104.0,
        UnitOfTemperature.FAHRENHEIT,
    )

    assert state.selected_heater_id == "H0001"
    assert state.active_heat_source is api_modules.models.HeatSource.GAS
    assert state.available_heaters[0].name == "Pentair MasterTemp"


def test_unknown_or_unselected_heater_has_no_active_source(
    api_modules, pool_object_factory, coordinator_factory
):
    body = pool_object_factory(heater="00000", htmode="0")
    coordinator = coordinator_factory([body])

    state = api_modules.body.build_body_state(
        coordinator,
        body,
        (),
        40.0,
        104.0,
        UnitOfTemperature.FAHRENHEIT,
    )

    assert state.selected_heater_id is None
    assert state.active_heat_source is None
    assert state.heat_mode is api_modules.models.HeatMode.OFF
