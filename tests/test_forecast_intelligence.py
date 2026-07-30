from datetime import datetime, timedelta, timezone

from poolos.forecast import ForecastConfidence, ForecastFreshness, ForecastSnapshot
from poolos.forecast_intelligence import (
    CoolingRisk,
    ForecastIntelligence,
    ForecastRecommendation,
    HeatingPenalty,
    SolarOpportunity,
)

NOW = datetime(2026, 7, 30, 18, 0, tzinfo=timezone.utc)


def snapshot(**changes):
    values = {
        "provider": "test-provider",
        "issued_at": NOW,
        "valid_from": NOW,
        "valid_until": NOW + timedelta(hours=12),
        "ambient_temperature_f": 75.0,
        "overnight_low_temperature_f": 68.0,
        "wind_speed_mph": 3.0,
        "cloud_cover_percent": 20.0,
        "solar_production_kw": 2.0,
        "provider_confidence": 0.9,
    }
    values.update(changes)
    return ForecastSnapshot(**values)


def test_classifies_heating_penalty_from_environmental_resistance():
    intelligence = ForecastIntelligence()
    assert intelligence.heating_penalty(snapshot()) is HeatingPenalty.LOW
    assert intelligence.heating_penalty(snapshot(ambient_temperature_f=60)) is HeatingPenalty.MODERATE
    assert intelligence.heating_penalty(snapshot(ambient_temperature_f=45)) is HeatingPenalty.HIGH
    assert intelligence.heating_penalty(
        snapshot(ambient_temperature_f=45, wind_speed_mph=16)
    ) is HeatingPenalty.SEVERE


def test_classifies_solar_production_opportunity():
    intelligence = ForecastIntelligence()
    assert intelligence.solar_opportunity(snapshot(solar_production_kw=0.5)) is SolarOpportunity.POOR
    assert intelligence.solar_opportunity(snapshot(solar_production_kw=2)) is SolarOpportunity.FAIR
    assert intelligence.solar_opportunity(snapshot(solar_production_kw=5)) is SolarOpportunity.GOOD
    assert intelligence.solar_opportunity(snapshot(solar_production_kw=9)) is SolarOpportunity.EXCELLENT
    assert intelligence.solar_opportunity(snapshot(solar_production_kw=None)) is SolarOpportunity.UNKNOWN


def test_classifies_overnight_cooling_risk():
    intelligence = ForecastIntelligence()
    assert intelligence.cooling_risk(snapshot()) is CoolingRisk.LOW
    assert intelligence.cooling_risk(snapshot(overnight_low_temperature_f=60)) is CoolingRisk.MODERATE
    assert intelligence.cooling_risk(snapshot(overnight_low_temperature_f=50)) is CoolingRisk.HIGH
    assert intelligence.cooling_risk(
        snapshot(overnight_low_temperature_f=40, wind_speed_mph=16)
    ) is CoolingRisk.SEVERE


def test_good_solar_and_mild_conditions_recommend_delay_for_solar():
    assessment = ForecastIntelligence().assess(snapshot(solar_production_kw=6), NOW)
    assert assessment.recommendation is ForecastRecommendation.DELAY_FOR_SOLAR
    assert assessment.freshness is ForecastFreshness.FRESH
    assert assessment.confidence is ForecastConfidence.HIGH


def test_cold_or_windy_forecast_recommends_early_start():
    assessment = ForecastIntelligence().assess(
        snapshot(ambient_temperature_f=45, solar_production_kw=0),
        NOW,
    )
    assert assessment.recommendation is ForecastRecommendation.START_EARLY
    assert assessment.heating_penalty is HeatingPenalty.HIGH


def test_aging_or_low_confidence_forecast_is_conservative():
    aging = snapshot(issued_at=NOW - timedelta(hours=2))
    low_confidence = snapshot(provider_confidence=0.2)
    assert ForecastIntelligence().assess(
        aging, NOW
    ).recommendation is ForecastRecommendation.PROCEED_CONSERVATIVELY
    assert ForecastIntelligence().assess(
        low_confidence, NOW
    ).recommendation is ForecastRecommendation.PROCEED_CONSERVATIVELY


def test_stale_and_expired_forecasts_wait_for_refresh():
    stale = snapshot(issued_at=NOW - timedelta(hours=4))
    expired = snapshot(issued_at=NOW - timedelta(hours=7))
    assert ForecastIntelligence().assess(
        stale, NOW
    ).recommendation is ForecastRecommendation.WAIT_FOR_REFRESH
    assert ForecastIntelligence().assess(
        expired, NOW
    ).recommendation is ForecastRecommendation.WAIT_FOR_REFRESH


def test_missing_optional_weather_data_remains_traceable():
    value = snapshot(
        ambient_temperature_f=None,
        overnight_low_temperature_f=None,
        wind_speed_mph=None,
        cloud_cover_percent=None,
        solar_production_kw=None,
    )
    assessment = ForecastIntelligence().assess(value, NOW)
    assert assessment.heating_penalty is HeatingPenalty.UNKNOWN
    assert assessment.cooling_risk is CoolingRisk.UNKNOWN
    assert assessment.solar_opportunity is SolarOpportunity.UNKNOWN
    assert assessment.recommendation is ForecastRecommendation.START_NORMAL
    assert len(assessment.reasons) == 3
