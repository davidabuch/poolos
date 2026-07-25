from dataclasses import FrozenInstanceError

import pytest

from poolos import BodyState, BodyType, TemperatureState


def test_temperature_state_creation() -> None:
    state = TemperatureState(
        current=86.5,
        target=90.0,
        heating=True,
    )

    assert state.current == 86.5
    assert state.target == 90.0
    assert state.heating is True


def test_body_state_creation() -> None:
    body = BodyState(
        body=BodyType.POOL,
        temperature=TemperatureState(
            current=82,
            target=88,
            heating=False,
        ),
        circulation_running=True,
        sanitizer_enabled=True,
    )

    assert body.body is BodyType.POOL
    assert body.temperature.current == 82
    assert body.circulation_running
    assert body.sanitizer_enabled


def test_models_are_immutable() -> None:
    state = TemperatureState(
        current=85,
        target=90,
        heating=False,
    )

    with pytest.raises(FrozenInstanceError):
        state.current = 90