"""Tests for PoolOS domain enumerations."""

from enum import Enum, IntEnum

from poolos import (
    BodyType,
    CommandPriority,
    EquipmentType,
    HeatingSource,
    PolicyPriority,
    RecommendationSeverity,
)


def test_body_type_values() -> None:
    """Body types expose stable serialized values."""

    assert BodyType.POOL.value == "pool"
    assert BodyType.SPA.value == "spa"


def test_equipment_type_values_are_unique() -> None:
    """Every equipment category has a unique serialized value."""

    values = [equipment_type.value for equipment_type in EquipmentType]

    assert len(values) == len(set(values))


def test_heating_source_values() -> None:
    """Heating sources expose stable serialized values."""

    assert HeatingSource.GAS.value == "gas"
    assert HeatingSource.SOLAR.value == "solar"
    assert HeatingSource.HEAT_PUMP.value == "heat_pump"
    assert HeatingSource.HYBRID.value == "hybrid"


def test_string_enums_are_strings() -> None:
    """String-backed enums can be used where serialized strings are expected."""

    assert isinstance(BodyType.POOL, str)
    assert isinstance(EquipmentType.PUMP, str)
    assert isinstance(HeatingSource.GAS, str)
    assert issubclass(BodyType, Enum)


def test_policy_priority_ordering() -> None:
    """Higher-priority policy categories have larger numeric values."""

    assert PolicyPriority.BACKGROUND < PolicyPriority.OPTIMIZATION
    assert PolicyPriority.OPTIMIZATION < PolicyPriority.USER_REQUEST
    assert PolicyPriority.USER_REQUEST < PolicyPriority.SAFETY
    assert PolicyPriority.SAFETY < PolicyPriority.EMERGENCY


def test_command_priority_ordering() -> None:
    """Higher-priority commands have larger numeric values."""

    assert CommandPriority.LOW < CommandPriority.NORMAL
    assert CommandPriority.NORMAL < CommandPriority.HIGH
    assert CommandPriority.HIGH < CommandPriority.CRITICAL


def test_recommendation_severity_ordering() -> None:
    """More serious recommendations have larger numeric values."""

    assert (
        RecommendationSeverity.INFORMATIONAL
        < RecommendationSeverity.NOTICE
    )
    assert RecommendationSeverity.NOTICE < RecommendationSeverity.WARNING
    assert RecommendationSeverity.WARNING < RecommendationSeverity.CRITICAL


def test_priority_enums_are_integer_enums() -> None:
    """Priority and severity values support numeric comparison."""

    assert issubclass(PolicyPriority, IntEnum)
    assert issubclass(CommandPriority, IntEnum)
    assert issubclass(RecommendationSeverity, IntEnum)


def test_public_package_exports() -> None:
    """The PoolOS package exposes its supported enum API."""

    import poolos

    assert poolos.__all__ == [
        "BodyType",
        "CommandPriority",
        "EquipmentType",
        "HeatingSource",
        "PolicyPriority",
        "RecommendationSeverity",
    ]