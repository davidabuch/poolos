"""Explainable behavioral inference from durable PoolOS observation history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import hashlib
import json
import math
import statistics
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .observations import RecordedObservationEvent

SCHEMA_VERSION = "1.0.0"


class InferredOperatingState(str, Enum):
    """Canonical inferred operating states kept separate from observed facts."""

    UNKNOWN = "UNKNOWN"
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    PRIMING = "PRIMING"
    FILTERING = "FILTERING"
    SOLAR_ASSIST = "SOLAR_ASSIST"
    HEATING = "HEATING"
    SPA = "SPA"
    IDLE = "IDLE"


@dataclass(frozen=True, slots=True)
class InferenceEvidence:
    """One durable observation event supporting an inference."""

    event_id: str
    recorded_at: datetime
    observation_ids: tuple[str, ...]
    summary: str


@dataclass(frozen=True, slots=True)
class InferredBehaviorEvent:
    """Explainable inferred transition with provenance back to raw evidence."""

    inference_id: str
    kind: str
    occurred_at: datetime
    confidence: float
    summary: str
    evidence_event_ids: tuple[str, ...]
    attributes: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_event_ids", tuple(self.evidence_event_ids))
        object.__setattr__(
            self,
            "attributes",
            MappingProxyType(dict(sorted(self.attributes.items()))),
        )


class SolarEpisodeState(str, Enum):
    """Whether an observed solar episode has an explicit deactivation."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class SolarEpisode:
    """One activation paired with its next observed deactivation, when present."""

    episode_id: str
    state: SolarEpisodeState
    activation_time: datetime
    deactivation_time: datetime | None
    duration_seconds: float | None
    activation_transition: InferredBehaviorEvent
    deactivation_transition: InferredBehaviorEvent | None
    source_event_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_event_ids", tuple(self.source_event_ids))

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "state": self.state.value,
            "activation_time": self.activation_time.isoformat(),
            "deactivation_time": (
                None if self.deactivation_time is None else self.deactivation_time.isoformat()
            ),
            "duration_seconds": self.duration_seconds,
            "activation_transition": _event_dict(self.activation_transition),
            "deactivation_transition": (
                None
                if self.deactivation_transition is None
                else _event_dict(self.deactivation_transition)
            ),
            "source_event_ids": list(self.source_event_ids),
        }


@dataclass(frozen=True, slots=True)
class SolarBehaviorInference:
    """Empirical solar transition model; never an asserted controller rule."""

    activation_samples: int
    deactivation_samples: int
    activation_differential_f: float | None
    deactivation_differential_f: float | None
    hysteresis_differential_f: float | None
    activation_roof_temperature_f: float | None
    deactivation_roof_temperature_f: float | None
    confidence: float
    assessment: str
    evidence_event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BehavioralInferenceReport:
    """Deterministic behavioral interpretation of a historical evidence window."""

    schema_version: str
    generated_from_start: datetime | None
    generated_from_end: datetime | None
    current_state: InferredOperatingState
    current_state_confidence: float
    events: tuple[InferredBehaviorEvent, ...]
    solar_episodes: tuple[SolarEpisode, ...]
    solar: SolarBehaviorInference
    source_event_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a stable, JSON-friendly read-only representation."""

        return {
            "schema_version": self.schema_version,
            "generated_from_start": self.generated_from_start.isoformat() if self.generated_from_start else None,
            "generated_from_end": self.generated_from_end.isoformat() if self.generated_from_end else None,
            "current_state": self.current_state.value,
            "current_state_confidence": self.current_state_confidence,
            "source_event_count": len(self.source_event_ids),
            "source_event_ids": list(self.source_event_ids),
            "events": [_event_dict(item) for item in self.events],
            "solar_episodes": [item.to_dict() for item in self.solar_episodes],
            "solar": {
                "activation_samples": self.solar.activation_samples,
                "deactivation_samples": self.solar.deactivation_samples,
                "activation_differential_f": self.solar.activation_differential_f,
                "deactivation_differential_f": self.solar.deactivation_differential_f,
                "hysteresis_differential_f": self.solar.hysteresis_differential_f,
                "activation_roof_temperature_f": self.solar.activation_roof_temperature_f,
                "deactivation_roof_temperature_f": self.solar.deactivation_roof_temperature_f,
                "confidence": self.solar.confidence,
                "assessment": self.solar.assessment,
                "evidence_event_ids": list(self.solar.evidence_event_ids),
            },
        }


@dataclass(frozen=True, slots=True)
class _Frame:
    event: RecordedObservationEvent
    values: Mapping[str, Any]
    units: Mapping[str, str | None]
    confidence: float


@dataclass(frozen=True, slots=True)
class _SolarSample:
    event_id: str
    active: bool
    roof_f: float | None
    pool_f: float | None

    @property
    def differential_f(self) -> float | None:
        if self.roof_f is None or self.pool_f is None:
            return None
        return self.roof_f - self.pool_f


class BehavioralInferenceEngine:
    """Infer operational behavior without mutating observations or issuing commands."""

    startup_window = timedelta(minutes=12)
    priming_drop_rpm = 300.0
    minimum_running_rpm = 100.0

    def infer(self, records: Iterable[RecordedObservationEvent]) -> BehavioralInferenceReport:
        """Infer behavior deterministically from durable observed evidence."""

        evidence = tuple(records)
        if any(
            item.recorded_at.tzinfo is None or item.recorded_at.utcoffset() is None
            for item in evidence
        ):
            raise ValueError("behavioral inference evidence timestamps must be timezone-aware")
        ordered = tuple(
            sorted(evidence, key=lambda item: (item.recorded_at, item.event_id))
        )
        if not ordered:
            return BehavioralInferenceReport(
                schema_version=SCHEMA_VERSION,
                generated_from_start=None,
                generated_from_end=None,
                current_state=InferredOperatingState.UNKNOWN,
                current_state_confidence=0.0,
                events=(),
                solar_episodes=(),
                solar=_empty_solar(),
                source_event_ids=(),
            )

        frames = tuple(_frame(item) for item in ordered)
        inferred: list[InferredBehaviorEvent] = []
        solar_samples: list[_SolarSample] = []
        previous: _Frame | None = None
        startup_at: datetime | None = None
        startup_peak_rpm: float | None = None
        startup_peak_event_id: str | None = None
        priming_reported = False

        for frame in frames:
            rpm = _number(frame.values.get("pump.rpm"))
            previous_rpm = None if previous is None else _number(previous.values.get("pump.rpm"))
            running = rpm is not None and rpm >= self.minimum_running_rpm
            was_running = previous_rpm is not None and previous_rpm >= self.minimum_running_rpm

            if previous_rpm is not None and running and not was_running:
                assert rpm is not None
                startup_at = frame.event.recorded_at
                startup_peak_rpm = rpm
                startup_peak_event_id = frame.event.event_id
                priming_reported = False
                inferred.append(
                    _inferred_event(
                        kind="PUMP_START",
                        frame=frame,
                        confidence=frame.confidence,
                        summary=f"Pump start observed at {int(round(rpm))} RPM.",
                        attributes={"observed_rpm": rpm},
                    )
                )
            elif running and startup_at is not None and frame.event.recorded_at - startup_at <= self.startup_window:
                if startup_peak_rpm is None or (rpm is not None and rpm > startup_peak_rpm):
                    startup_peak_rpm = rpm
                    startup_peak_event_id = frame.event.event_id
                if (
                    not priming_reported
                    and startup_peak_rpm is not None
                    and rpm is not None
                    and startup_peak_rpm - rpm >= self.priming_drop_rpm
                ):
                    evidence_ids = tuple(
                        item
                        for item in (startup_peak_event_id, frame.event.event_id)
                        if item is not None
                    )
                    inferred.append(
                        _inferred_event(
                            kind="PUMP_PRIMING_INFERRED",
                            frame=frame,
                            confidence=min(frame.confidence, 0.85),
                            summary=(
                                f"Startup priming inferred from a {int(round(startup_peak_rpm))} RPM peak "
                                f"settling to {int(round(rpm))} RPM."
                            ),
                            attributes={
                                "peak_rpm": startup_peak_rpm,
                                "settled_rpm": rpm,
                                "elapsed_seconds": (frame.event.recorded_at - startup_at).total_seconds(),
                            },
                            evidence_event_ids=evidence_ids,
                        )
                    )
                    priming_reported = True
                    startup_at = None
            elif not running:
                startup_at = None
                startup_peak_rpm = None
                startup_peak_event_id = None
                priming_reported = False

            solar_now = _boolean(frame.values.get("solar.active"))
            solar_previous = None if previous is None else _boolean(previous.values.get("solar.active"))
            if solar_now is not None and solar_previous is not None and solar_now != solar_previous:
                sample = _SolarSample(
                    event_id=frame.event.event_id,
                    active=solar_now,
                    roof_f=_number(frame.values.get("solar.temperature")),
                    pool_f=_number(frame.values.get("pool.temperature")),
                )
                solar_samples.append(sample)
                attributes = _solar_transition_attributes(frame, sample, rpm)
                inferred.append(
                    _inferred_event(
                        kind="SOLAR_ACTIVATED" if solar_now else "SOLAR_DEACTIVATED",
                        frame=frame,
                        confidence=frame.confidence,
                        summary=_solar_summary(sample),
                        attributes=attributes,
                    )
                )

            for observation_id, kind, label in (
                ("heater.active", "HEATER_ACTIVATED", "Heater"),
                ("spa.active", "SPA_ACTIVATED", "Spa"),
            ):
                now_value = _boolean(frame.values.get(observation_id))
                previous_value = None if previous is None else _boolean(previous.values.get(observation_id))
                if now_value is True and previous_value is False:
                    inferred.append(
                        _inferred_event(
                            kind=kind,
                            frame=frame,
                            confidence=frame.confidence,
                            summary=f"{label} activation observed.",
                            attributes={"pump_rpm": rpm},
                        )
                    )

            previous = frame

        current_state, state_confidence = self._current_state(frames, inferred)
        ordered_events = tuple(
            sorted(inferred, key=lambda item: (item.occurred_at, item.inference_id))
        )
        return BehavioralInferenceReport(
            schema_version=SCHEMA_VERSION,
            generated_from_start=frames[0].event.recorded_at,
            generated_from_end=frames[-1].event.recorded_at,
            current_state=current_state,
            current_state_confidence=state_confidence,
            events=ordered_events,
            solar_episodes=_solar_episodes(ordered_events),
            solar=_solar_inference(solar_samples),
            source_event_ids=tuple(item.event.event_id for item in frames),
        )

    def _current_state(
        self,
        frames: tuple[_Frame, ...],
        inferred: list[InferredBehaviorEvent],
    ) -> tuple[InferredOperatingState, float]:
        frame = frames[-1]
        values = frame.values
        rpm = _number(values.get("pump.rpm"))
        if rpm is None:
            return InferredOperatingState.UNKNOWN, min(frame.confidence, 0.4)
        if rpm < self.minimum_running_rpm:
            return InferredOperatingState.STOPPED, frame.confidence
        if _boolean(values.get("spa.active")) is True:
            return InferredOperatingState.SPA, frame.confidence
        if _boolean(values.get("solar.active")) is True:
            return InferredOperatingState.SOLAR_ASSIST, frame.confidence
        if _boolean(values.get("heater.active")) is True:
            return InferredOperatingState.HEATING, frame.confidence
        if _boolean(values.get("pool.active")) is True:
            if inferred and inferred[-1].kind == "PUMP_START" and inferred[-1].occurred_at == frame.event.recorded_at:
                return InferredOperatingState.STARTING, min(frame.confidence, 0.9)
            return InferredOperatingState.FILTERING, frame.confidence
        return InferredOperatingState.IDLE, min(frame.confidence, 0.8)


def _frame(event: RecordedObservationEvent) -> _Frame:
    values: dict[str, Any] = {}
    units: dict[str, str | None] = {}
    confidences: list[float] = []
    for observation in event.observations:
        observation_id = str(observation.get("observation_id", ""))
        if not observation_id:
            continue
        values[observation_id] = observation.get("value")
        raw_unit = observation.get("unit")
        units[observation_id] = None if raw_unit is None else str(raw_unit)
        confidence = _number(observation.get("confidence"))
        if confidence is not None:
            confidences.append(max(0.0, min(1.0, confidence)))
    healthy = bool(event.health.get("healthy", False))
    base = min(confidences) if confidences else 0.5
    if not healthy:
        base = min(base, 0.5)
    return _Frame(event=event, values=values, units=units, confidence=base)


def _solar_transition_attributes(
    frame: _Frame,
    sample: _SolarSample,
    rpm: float | None,
) -> dict[str, Any]:
    water_f = _number(frame.values.get("water.temperature"))
    attributes: dict[str, Any] = {
        "solar_temperature_f": sample.roof_f,
        "pool_temperature_f": sample.pool_f,
        "temperature_differential_f": sample.differential_f,
        "roof_to_pool_differential_f": sample.differential_f,
        "water_temperature_f": water_f,
        "roof_to_water_differential_f": (
            None if sample.roof_f is None or water_f is None else sample.roof_f - water_f
        ),
        "air_temperature_f": _number(frame.values.get("air.temperature")),
        "pool_target_temperature_f": _number(
            frame.values.get("pool.target_temperature")
        ),
        "pool_heating_demand_active": _boolean(
            frame.values.get("pool.heating_demand_active")
        ),
        "spa_active": _boolean(frame.values.get("spa.active")),
        "pool_active": _boolean(frame.values.get("pool.active")),
        "heater_active": _boolean(frame.values.get("heater.active")),
        "solar_preferred_active": _boolean(
            frame.values.get("solar_preferred.active")
        ),
        "pump_rpm": rpm,
        "pump_gpm": _number(frame.values.get("pump.gpm")),
        "pump_power": _number(frame.values.get("pump.power")),
        "pump_power_unit": frame.units.get("pump.power"),
        "time_of_day": frame.event.recorded_at.timetz().isoformat(),
        "utc_offset_minutes": int(
            (frame.event.recorded_at.utcoffset() or timedelta(0)).total_seconds() / 60
        ),
    }
    return {key: value for key, value in attributes.items() if value is not None}


def _solar_episodes(
    events: tuple[InferredBehaviorEvent, ...],
) -> tuple[SolarEpisode, ...]:
    episodes: list[SolarEpisode] = []
    activation: InferredBehaviorEvent | None = None
    for event in events:
        if event.kind == "SOLAR_ACTIVATED":
            if activation is None:
                activation = event
            continue
        if event.kind != "SOLAR_DEACTIVATED" or activation is None:
            continue
        episodes.append(_solar_episode(activation, event))
        activation = None
    if activation is not None:
        episodes.append(_solar_episode(activation, None))
    return tuple(episodes)


def _solar_episode(
    activation: InferredBehaviorEvent,
    deactivation: InferredBehaviorEvent | None,
) -> SolarEpisode:
    source_ids = activation.evidence_event_ids + (
        () if deactivation is None else deactivation.evidence_event_ids
    )
    payload = {
        "activation_id": activation.inference_id,
    }
    episode_id = "solar-episode-" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return SolarEpisode(
        episode_id=episode_id,
        state=(
            SolarEpisodeState.OPEN
            if deactivation is None
            else SolarEpisodeState.CLOSED
        ),
        activation_time=activation.occurred_at,
        deactivation_time=None if deactivation is None else deactivation.occurred_at,
        duration_seconds=(
            None
            if deactivation is None
            else (deactivation.occurred_at - activation.occurred_at).total_seconds()
        ),
        activation_transition=activation,
        deactivation_transition=deactivation,
        source_event_ids=source_ids,
    )


def _event_dict(item: InferredBehaviorEvent) -> dict[str, Any]:
    return {
        "inference_id": item.inference_id,
        "kind": item.kind,
        "occurred_at": item.occurred_at.isoformat(),
        "confidence": item.confidence,
        "summary": item.summary,
        "evidence_event_ids": list(item.evidence_event_ids),
        "attributes": dict(item.attributes),
    }


def _solar_inference(samples: list[_SolarSample]) -> SolarBehaviorInference:
    activation = [item for item in samples if item.active]
    deactivation = [item for item in samples if not item.active]
    activation_diffs = [item.differential_f for item in activation if item.differential_f is not None]
    deactivation_diffs = [item.differential_f for item in deactivation if item.differential_f is not None]
    activation_roofs = [item.roof_f for item in activation if item.roof_f is not None]
    deactivation_roofs = [item.roof_f for item in deactivation if item.roof_f is not None]
    activation_median = _median(activation_diffs)
    deactivation_median = _median(deactivation_diffs)
    hysteresis = None
    if activation_median is not None and deactivation_median is not None:
        hysteresis = activation_median - deactivation_median
    count = min(len(activation), len(deactivation)) if deactivation else len(activation)
    confidence = min(0.9, 0.25 + 0.12 * count)
    if not activation_diffs:
        confidence = min(confidence, 0.35)
    if len(activation) >= 3 and len(deactivation) >= 3 and hysteresis is not None:
        assessment = (
            "Repeated solar transitions support a provisional hysteresis pattern."
            if hysteresis > 0.5
            else "Repeated solar transitions do not yet show a clear differential hysteresis gap."
        )
    elif samples:
        assessment = "Solar transitions observed; more repeated-day evidence is required before inferring a controller threshold."
    else:
        assessment = "No solar transitions were present in the evidence window."
        confidence = 0.0
    return SolarBehaviorInference(
        activation_samples=len(activation),
        deactivation_samples=len(deactivation),
        activation_differential_f=_rounded(activation_median),
        deactivation_differential_f=_rounded(deactivation_median),
        hysteresis_differential_f=_rounded(hysteresis),
        activation_roof_temperature_f=_rounded(_median(activation_roofs)),
        deactivation_roof_temperature_f=_rounded(_median(deactivation_roofs)),
        confidence=round(confidence, 3),
        assessment=assessment,
        evidence_event_ids=tuple(item.event_id for item in samples),
    )


def _solar_summary(sample: _SolarSample) -> str:
    action = "activated" if sample.active else "deactivated"
    if sample.differential_f is None:
        return f"Solar {action}; temperature differential was unavailable."
    return f"Solar {action} at an observed roof-to-pool differential of {sample.differential_f:.1f}°F."


def _empty_solar() -> SolarBehaviorInference:
    return SolarBehaviorInference(0, 0, None, None, None, None, None, 0.0, "No solar transitions were present in the evidence window.", ())


def _inferred_event(
    *,
    kind: str,
    frame: _Frame,
    confidence: float,
    summary: str,
    attributes: Mapping[str, Any],
    evidence_event_ids: tuple[str, ...] | None = None,
) -> InferredBehaviorEvent:
    evidence_ids = evidence_event_ids or (frame.event.event_id,)
    identity_payload = {
        "kind": kind,
        "occurred_at": frame.event.recorded_at.isoformat(),
        "evidence_event_ids": list(evidence_ids),
        "attributes": dict(sorted(attributes.items())),
    }
    inference_id = hashlib.sha256(
        json.dumps(identity_payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return InferredBehaviorEvent(
        inference_id=inference_id,
        kind=kind,
        occurred_at=frame.event.recorded_at,
        confidence=round(max(0.0, min(1.0, confidence)), 3),
        summary=summary,
        evidence_event_ids=evidence_ids,
        attributes=dict(sorted(attributes.items())),
    )


def _boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"on", "true", "yes", "1"}:
            return True
        if normalized in {"off", "false", "no", "0"}:
            return False
    return None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


__all__ = [
    "BehavioralInferenceEngine",
    "BehavioralInferenceReport",
    "InferenceEvidence",
    "InferredBehaviorEvent",
    "InferredOperatingState",
    "SCHEMA_VERSION",
    "SolarBehaviorInference",
    "SolarEpisode",
    "SolarEpisodeState",
]
