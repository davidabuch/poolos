"""Deterministic planning intelligence derived from canonical forecasts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .forecast import (
    ForecastConfidence,
    ForecastFreshness,
    ForecastFreshnessPolicy,
    ForecastSnapshot,
)


class HeatingPenalty(str, Enum):
    """Expected environmental resistance to heating."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    SEVERE = "severe"
    UNKNOWN = "unknown"


class SolarOpportunity(str, Enum):
    """Expected useful solar-production opportunity."""

    POOR = "poor"
    FAIR = "fair"
    GOOD = "good"
    EXCELLENT = "excellent"
    UNKNOWN = "unknown"


class CoolingRisk(str, Enum):
    """Expected overnight water-temperature loss risk."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    SEVERE = "severe"
    UNKNOWN = "unknown"


class ForecastRecommendation(str, Enum):
    """Typed planning recommendation produced from forecast intelligence."""

    START_EARLY = "start_early"
    START_NORMAL = "start_normal"
    DELAY_FOR_SOLAR = "delay_for_solar"
    WAIT_FOR_REFRESH = "wait_for_refresh"
    PROCEED_CONSERVATIVELY = "proceed_conservatively"


@dataclass(frozen=True, slots=True)
class ForecastAssessment:
    """Traceable planning facts derived from one forecast snapshot."""

    freshness: ForecastFreshness
    confidence: ForecastConfidence
    heating_penalty: HeatingPenalty
    solar_opportunity: SolarOpportunity
    cooling_risk: CoolingRisk
    recommendation: ForecastRecommendation
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ForecastIntelligence:
    """Convert normalized weather facts into deterministic planning signals."""

    freshness_policy: ForecastFreshnessPolicy = ForecastFreshnessPolicy()

    @staticmethod
    def heating_penalty(snapshot: ForecastSnapshot) -> HeatingPenalty:
        score = 0
        facts = 0
        if snapshot.ambient_temperature_f is not None:
            facts += 1
            if snapshot.ambient_temperature_f < 50:
                score += 2
            elif snapshot.ambient_temperature_f < 65:
                score += 1
        if snapshot.wind_speed_mph is not None:
            facts += 1
            if snapshot.wind_speed_mph >= 15:
                score += 2
            elif snapshot.wind_speed_mph >= 8:
                score += 1
        if snapshot.cloud_cover_percent is not None:
            facts += 1
            if snapshot.cloud_cover_percent >= 80:
                score += 1
        if facts == 0:
            return HeatingPenalty.UNKNOWN
        if score >= 4:
            return HeatingPenalty.SEVERE
        if score >= 2:
            return HeatingPenalty.HIGH
        if score == 1:
            return HeatingPenalty.MODERATE
        return HeatingPenalty.LOW

    @staticmethod
    def solar_opportunity(snapshot: ForecastSnapshot) -> SolarOpportunity:
        production = snapshot.solar_production_kw
        if production is None:
            return SolarOpportunity.UNKNOWN
        if production >= 8:
            return SolarOpportunity.EXCELLENT
        if production >= 4:
            return SolarOpportunity.GOOD
        if production >= 1:
            return SolarOpportunity.FAIR
        return SolarOpportunity.POOR

    @staticmethod
    def cooling_risk(snapshot: ForecastSnapshot) -> CoolingRisk:
        score = 0
        facts = 0
        if snapshot.overnight_low_temperature_f is not None:
            facts += 1
            if snapshot.overnight_low_temperature_f < 45:
                score += 3
            elif snapshot.overnight_low_temperature_f < 55:
                score += 2
            elif snapshot.overnight_low_temperature_f < 65:
                score += 1
        if snapshot.wind_speed_mph is not None:
            facts += 1
            if snapshot.wind_speed_mph >= 15:
                score += 2
            elif snapshot.wind_speed_mph >= 8:
                score += 1
        if facts == 0:
            return CoolingRisk.UNKNOWN
        if score >= 4:
            return CoolingRisk.SEVERE
        if score >= 2:
            return CoolingRisk.HIGH
        if score == 1:
            return CoolingRisk.MODERATE
        return CoolingRisk.LOW

    def assess(self, snapshot: ForecastSnapshot, now: datetime) -> ForecastAssessment:
        freshness = snapshot.freshness(now, self.freshness_policy)
        confidence = snapshot.confidence
        heating = self.heating_penalty(snapshot)
        solar = self.solar_opportunity(snapshot)
        cooling = self.cooling_risk(snapshot)
        reasons: list[str] = [
            f"Forecast freshness is {freshness.value}.",
            f"Forecast confidence is {confidence.value}.",
        ]

        if freshness in {ForecastFreshness.STALE, ForecastFreshness.EXPIRED}:
            recommendation = ForecastRecommendation.WAIT_FOR_REFRESH
            reasons.append("Forecast age is too high for predictive schedule changes.")
        elif freshness is ForecastFreshness.AGING or confidence in {
            ForecastConfidence.LOW,
            ForecastConfidence.UNKNOWN,
        }:
            recommendation = ForecastRecommendation.PROCEED_CONSERVATIVELY
            reasons.append("Forecast uncertainty requires conservative planning.")
        elif heating in {HeatingPenalty.HIGH, HeatingPenalty.SEVERE} or cooling in {
            CoolingRisk.HIGH,
            CoolingRisk.SEVERE,
        }:
            recommendation = ForecastRecommendation.START_EARLY
            reasons.append("Heating resistance or cooling risk supports an earlier start.")
        elif solar in {SolarOpportunity.GOOD, SolarOpportunity.EXCELLENT} and heating in {
            HeatingPenalty.LOW,
            HeatingPenalty.MODERATE,
        }:
            recommendation = ForecastRecommendation.DELAY_FOR_SOLAR
            reasons.append("Useful solar production supports delaying conventional heating.")
        else:
            recommendation = ForecastRecommendation.START_NORMAL
            reasons.append("Forecast conditions do not require a schedule adjustment.")

        return ForecastAssessment(
            freshness,
            confidence,
            heating,
            solar,
            cooling,
            recommendation,
            tuple(reasons),
        )
