import pytest

from poolos.domain import (
    ConfidenceBand,
    Evidence,
    Feature,
    HydraulicRoute,
    Installation,
    Observation,
    PoolSystem,
    TruthLevel,
)


def test_installation_supports_multiple_independent_systems():
    main = PoolSystem(id="main", name="Main Pool/Spa", body_ids=frozenset({"pool", "spa"}))
    detached = PoolSystem(id="detached", name="Detached Spa", body_ids=frozenset({"spa2"}))
    installation = Installation(id="home", name="Residence", systems=(main, detached))

    assert installation.get_system("main") is main
    assert installation.get_system("detached") is detached


def test_duplicate_system_ids_are_rejected():
    first = PoolSystem(id="main", name="One")
    second = PoolSystem(id="main", name="Two")
    with pytest.raises(ValueError):
        Installation(id="home", name="Residence", systems=(first, second))


def test_route_and_feature_are_separate_concepts():
    route = HydraulicRoute(
        id="waterfall_route",
        name="Waterfall Route",
        suction_body_ids=frozenset({"pool"}),
        return_body_ids=frozenset({"pool"}),
        required_equipment_ids=frozenset({"main_pump", "waterfall_valve"}),
        minimum_pump_rpm=2200,
    )
    feature = Feature(
        id="waterfall",
        name="Waterfall",
        route_id=route.id,
        required_equipment_ids=route.required_equipment_ids,
        minimum_pump_rpm=2200,
    )

    assert feature.route_id == route.id
    assert route.minimum_pump_rpm == 2200


def test_observation_is_explainable_and_confidence_banded():
    observation = Observation(
        name="filter_health",
        value=0.84,
        unit="fraction",
        truth_level=TruthLevel.LEARNED,
        confidence=0.93,
        source="runtime_memory",
        evidence=(
            Evidence("Pump power increased 11% from clean-filter baseline", 0.9),
            Evidence("No heater flow interruptions", 0.7),
        ),
    )

    assert observation.confidence_band is ConfidenceBand.HIGH
    explanation = observation.explain()
    assert explanation["truth_level"] == "learned"
    assert explanation["confidence"] == 0.93
    assert len(explanation["evidence"]) == 2


def test_invalid_confidence_is_rejected():
    with pytest.raises(ValueError):
        Observation("bad", 1, None, TruthLevel.PREDICTED, confidence=1.2)
