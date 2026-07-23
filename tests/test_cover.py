from dataclasses import FrozenInstanceError

import pytest


def test_builds_closed_cover_when_status_matches_normal(
    api_modules, cover_object_factory
):
    cover = cover_object_factory(status="ON", normal="ON")

    state = api_modules.cover.build_cover_state(cover)

    assert state.id == "X0001"
    assert state.name == "Pool Cover"
    assert state.subtype == "COVER"
    assert state.is_closed is True
    assert state.status_is_on is True
    assert state.normal_is_on is True


def test_builds_open_cover_when_status_differs_from_normal(
    api_modules, cover_object_factory
):
    cover = cover_object_factory(status="OFF", normal="ON")

    state = api_modules.cover.build_cover_state(cover)

    assert state.is_closed is False
    assert state.status_is_on is False
    assert state.normal_is_on is True


def test_supports_normally_open_cover(api_modules, cover_object_factory):
    closed = cover_object_factory(status="OFF", normal="OFF")
    opened = cover_object_factory(status="ON", normal="OFF")

    assert api_modules.cover.build_cover_state(closed).is_closed is True
    assert api_modules.cover.build_cover_state(opened).is_closed is False


@pytest.mark.parametrize(
    ("status", "normal"),
    [
        (None, "ON"),
        ("ON", None),
        ("unexpected", "ON"),
        ("OFF", "unexpected"),
    ],
)
def test_unknown_inputs_do_not_fabricate_position(
    api_modules, cover_object_factory, status, normal
):
    cover = cover_object_factory(status=status, normal=normal)

    state = api_modules.cover.build_cover_state(cover)

    assert state.is_closed is None


def test_normalizes_case_and_whitespace(api_modules, cover_object_factory):
    cover = cover_object_factory(status=" on ", normal="ON")

    state = api_modules.cover.build_cover_state(cover)

    assert state.is_closed is True
    assert state.status_is_on is True


def test_cover_state_is_immutable(api_modules, cover_object_factory):
    state = api_modules.cover.build_cover_state(cover_object_factory())

    with pytest.raises(FrozenInstanceError):
        state.is_closed = False
