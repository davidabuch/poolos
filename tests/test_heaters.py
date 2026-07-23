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


def test_gas_solar_and_solar_preferred_are_distinct_modes(
    api_modules,
    pool_object_factory,
    heater_object_factory,
    coordinator_factory,
):
    body = pool_object_factory(heater="H0003")
    gas = heater_object_factory("H0001", name="Gas Heater", subtype="GAS")
    solar = heater_object_factory("H0002", name="Solar Panels", subtype="SOLAR")
    preferred = heater_object_factory(
        "H0003", name="Solar Preferred", subtype="SOLARPREF"
    )
    coordinator = coordinator_factory([body, gas, solar, preferred])
    coordinator.heaters_by_body[body.objnam] = (
        gas.objnam,
        solar.objnam,
        preferred.objnam,
    )

    state = api_modules.body.build_body_state(
        coordinator,
        body,
        coordinator.heaters_by_body[body.objnam],
        40.0,
        104.0,
        UnitOfTemperature.FAHRENHEIT,
    )

    assert state.selected_heat_mode is api_modules.models.BodyHeatMode.SOLAR_PREFERRED
    assert state.available_heat_modes == (
        api_modules.models.BodyHeatMode.OFF,
        api_modules.models.BodyHeatMode.GAS,
        api_modules.models.BodyHeatMode.SOLAR,
        api_modules.models.BodyHeatMode.SOLAR_PREFERRED,
    )


def test_no_heat_selection_is_explicit_off_mode(
    api_modules, pool_object_factory, heater_object_factory, coordinator_factory
):
    body = pool_object_factory(heater="00000", htmode="0")
    gas = heater_object_factory("H0001", name="Gas Heater", subtype="GAS")
    solar = heater_object_factory("H0002", name="Solar Panels", subtype="SOLAR")
    coordinator = coordinator_factory([body, gas, solar])
    coordinator.heaters_by_body[body.objnam] = (gas.objnam, solar.objnam)

    state = api_modules.body.build_body_state(
        coordinator,
        body,
        coordinator.heaters_by_body[body.objnam],
        40.0,
        104.0,
        UnitOfTemperature.FAHRENHEIT,
    )

    assert state.selected_heat_mode is api_modules.models.BodyHeatMode.OFF
    assert state.available_heat_modes[0] is api_modules.models.BodyHeatMode.OFF
