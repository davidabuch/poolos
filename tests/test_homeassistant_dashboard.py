from datetime import datetime, timezone

from poolos.homeassistant import (
    DashboardComparisonStatus,
    DashboardDriftPolicy,
    HomeAssistantEntityCatalog,
    HomeAssistantEntityClass,
    HomeAssistantEntityDefinition,
    HomeAssistantSimulationDashboard,
    HomeAssistantValueType,
)
from poolos.observations import (
    ObservationQuality,
    ObservationSourceKind,
    ObservationStore,
    PoolObservation,
    TruthLevel,
)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


def catalog() -> HomeAssistantEntityCatalog:
    return HomeAssistantEntityCatalog.from_definitions(
        [
            HomeAssistantEntityDefinition(
                observation_id="pool.temperature",
                value_type=HomeAssistantValueType.FLOAT,
                entity_class=HomeAssistantEntityClass.SENSOR,
                unit="°F",
                observed_entity_id="sensor.pool_temperature",
                simulated_entity_id="sensor.poolos_sim_pool_temperature",
                friendly_name="PoolOS Sim Pool Temperature",
            ),
            HomeAssistantEntityDefinition(
                observation_id="pool.pump_running",
                value_type=HomeAssistantValueType.BOOLEAN,
                entity_class=HomeAssistantEntityClass.BINARY_SENSOR,
                observed_entity_id="binary_sensor.pool_pump_running",
                simulated_entity_id="binary_sensor.poolos_sim_pool_pump_running",
                friendly_name="PoolOS Sim Pump Running",
            ),
        ]
    )


def observation(observation_id: str, value: object, kind: ObservationSourceKind):
    return PoolObservation(
        observation_id=observation_id,
        value=value,
        observed_at=NOW,
        source_kind=kind,
        source_id=kind.value,
        truth_level=(
            TruthLevel.PREDICTED
            if kind is ObservationSourceKind.SIMULATED
            else TruthLevel.MEASURED
        ),
        quality=ObservationQuality.GOOD,
    )


def test_dashboard_marks_numeric_values_within_tolerance_as_match():
    store = ObservationStore()
    store.extend(
        [
            observation("pool.temperature", 84.0, ObservationSourceKind.LIVE),
            observation("pool.temperature", 84.4, ObservationSourceKind.SIMULATED),
        ]
    )
    dashboard = HomeAssistantSimulationDashboard(
        catalog(), DashboardDriftPolicy(tolerances={"pool.temperature": 0.5})
    )

    comparison = dashboard.comparisons(store)[0]

    assert comparison.status is DashboardComparisonStatus.MATCH
    assert comparison.delta == 0.4000000000000057
    assert comparison.tolerance == 0.5


def test_dashboard_marks_numeric_values_outside_tolerance_as_drift():
    store = ObservationStore()
    store.extend(
        [
            observation("pool.temperature", 84.0, ObservationSourceKind.LIVE),
            observation("pool.temperature", 86.0, ObservationSourceKind.SIMULATED),
        ]
    )

    comparison = HomeAssistantSimulationDashboard(catalog()).comparisons(store)[0]

    assert comparison.status is DashboardComparisonStatus.DRIFT
    assert comparison.delta == 2.0


def test_dashboard_reports_live_only_and_simulated_only_rows():
    store = ObservationStore()
    store.extend(
        [
            observation("pool.temperature", 84.0, ObservationSourceKind.LIVE),
            observation("pool.pump_running", True, ObservationSourceKind.SIMULATED),
        ]
    )

    rows = HomeAssistantSimulationDashboard(catalog()).comparisons(store)

    assert [row.status for row in rows] == [
        DashboardComparisonStatus.LIVE_ONLY,
        DashboardComparisonStatus.SIMULATED_ONLY,
    ]


def test_dashboard_compares_boolean_values_without_numeric_coercion():
    store = ObservationStore()
    store.extend(
        [
            observation("pool.pump_running", True, ObservationSourceKind.LIVE),
            observation("pool.pump_running", False, ObservationSourceKind.SIMULATED),
        ]
    )

    row = HomeAssistantSimulationDashboard(catalog()).comparisons(store)[1]

    assert row.status is DashboardComparisonStatus.DRIFT
    assert row.delta is None


def test_dashboard_summary_is_stable_and_read_only():
    summary = HomeAssistantSimulationDashboard(catalog()).summary(ObservationStore())

    assert summary[DashboardComparisonStatus.UNAVAILABLE.value] == 2
