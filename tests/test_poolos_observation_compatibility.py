from poolos import PoolObservation
from poolos.domain import Observation
from poolos.observations import Observation as ObservationCompatibilityAlias
from poolos.observations import TruthLevel


def test_legacy_observation_name_is_exact_canonical_type_alias():
    assert Observation is PoolObservation
    assert ObservationCompatibilityAlias is PoolObservation


def test_legacy_constructor_creates_canonical_pool_observation():
    observation = Observation(
        name="pool.water_temperature",
        value=86.0,
        unit="degF",
        truth_level=TruthLevel.MEASURED,
    )

    assert type(observation) is PoolObservation
    assert isinstance(observation, PoolObservation)
