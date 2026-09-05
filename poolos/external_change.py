"""Bounded classification of authoritative native changes outside PoolOS.

The classifier is observational.  It does not own a command port and cannot
reconcile equipment.  A RECONCILE result means current drift/readiness only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4

from .intellicenter_readonly import (
    NativeIntelliCenterObservationSnapshot,
    NativeIntelliCenterTransportSnapshot,
    NativeRawObject,
)
from .physical_command_authority import (
    NativeConsequenceAttribution,
    PoolOSPhysicalCommandAuthority,
)


class ExternalChangePolicy(StrEnum):
    RECONCILE = "reconcile"
    ADOPT = "adopt"
    ACCEPT = "accept"
    OBSERVE = "observe"


class ExternalSemanticEventType(StrEnum):
    NATIVE_VALUE_CHANGED = "native_value_changed"
    SCHEDULE_CREATED = "schedule_created"
    SCHEDULE_MODIFIED = "schedule_modified"
    SCHEDULE_DELETED = "schedule_deleted"


@dataclass(frozen=True, slots=True)
class ExternalOwnershipContext:
    """Current explicit ownership; writable does not imply owned."""

    intended_values: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "intended_values", MappingProxyType(dict(self.intended_values))
        )


@dataclass(frozen=True, slots=True)
class ExternalChangeEvent:
    """One bounded semantic transition suitable for Home Assistant events."""

    concept: str
    semantic_event_type: ExternalSemanticEventType
    native_object_id: str | None
    previous_value: Any
    new_value: Any
    observed_at: datetime
    external_policy: ExternalChangePolicy
    action_taken: str
    notification_recommended: bool
    reconciliation_required: bool
    intended_value: Any = None
    reason_code: str = "external_unattributed_native_change"
    maintenance_mode: bool = False
    changed_fields: tuple[str, ...] = ()
    event_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("external event observed_at must be timezone-aware")
        object.__setattr__(self, "changed_fields", tuple(self.changed_fields[:24]))

    def as_event_data(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "event_id": self.event_id,
                "concept": self.concept,
                "semantic_event_type": self.semantic_event_type.value,
                "native_object_id": self.native_object_id,
                "previous_value": _bounded_value(self.previous_value),
                "new_value": _bounded_value(self.new_value),
                "observed_at": self.observed_at.isoformat(),
                "maintenance_mode": self.maintenance_mode,
                "external_policy": self.external_policy.value,
                "action_taken": self.action_taken,
                "notification_recommended": self.notification_recommended,
                "reconciliation_required": self.reconciliation_required,
                "intended_value": _bounded_value(self.intended_value),
                "reason_code": self.reason_code,
                "changed_fields": list(self.changed_fields),
            }
        )


@dataclass(frozen=True, slots=True)
class ExternalChangeBatch:
    events: tuple[ExternalChangeEvent, ...]
    correlated_consequences: tuple[NativeConsequenceAttribution, ...] = ()


THERMAL_RUNTIME_TAKEOVER_CONCEPTS = frozenset(
    {
        "pool.active",
        "spa.active",
        "pump.rpm",
        "pump_circuit.p0102.configured_speed_rpm",
        "pool.raw_heater_id",
        "spa.raw_heater_id",
        "waterfall.active",
        "jets.active",
        "slide.active",
    }
)

POOL_CIRCULATION_TAKEOVER_CONCEPTS = (
    THERMAL_RUNTIME_TAKEOVER_CONCEPTS - frozenset({"spa.raw_heater_id"})
)


@dataclass(slots=True)
class ThermalRuntimeExternalChangeEvidence:
    """Retain one latest takeover event per canonical thermal/hydraulic concept."""

    _retained_by_concept: dict[str, ExternalChangeEvent] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def reset(self) -> None:
        """Discard retained evidence at a connection-generation boundary."""

        self._retained_by_concept.clear()

    def update(self, batch: ExternalChangeBatch) -> ExternalChangeBatch:
        """Return bounded evidence without losing earlier takeover facts."""

        transient: list[ExternalChangeEvent] = []
        for event in batch.events:
            if event.concept in THERMAL_RUNTIME_TAKEOVER_CONCEPTS:
                self._retained_by_concept.setdefault(event.concept, event)
            else:
                transient.append(event)

        retained = tuple(
            self._retained_by_concept[concept]
            for concept in sorted(self._retained_by_concept)
        )
        return ExternalChangeBatch(
            (*retained, *transient),
            batch.correlated_consequences,
        )

    @property
    def retained_count(self) -> int:
        return len(self._retained_by_concept)


_POLICIES: Mapping[str, tuple[ExternalChangePolicy, bool]] = MappingProxyType(
    {
        "pool.active": (ExternalChangePolicy.ACCEPT, True),
        "spa.active": (ExternalChangePolicy.ACCEPT, False),
        "pool.target_temperature": (ExternalChangePolicy.ADOPT, True),
        "spa.target_temperature": (ExternalChangePolicy.ADOPT, False),
        "intellichlor.pool_output_percent": (ExternalChangePolicy.ADOPT, True),
        "intellichlor.spa_output_percent": (ExternalChangePolicy.ADOPT, True),
        "pool_light.active": (ExternalChangePolicy.ACCEPT, False),
        "pool_light.effect": (ExternalChangePolicy.ACCEPT, False),
        "jets.active": (ExternalChangePolicy.ACCEPT, False),
        "waterfall.active": (ExternalChangePolicy.ACCEPT, False),
        "slide.active": (ExternalChangePolicy.ACCEPT, False),
        "freeze.active": (ExternalChangePolicy.OBSERVE, True),
        "intellicenter.system_mode": (ExternalChangePolicy.OBSERVE, True),
        "intellicenter.firmware_version": (ExternalChangePolicy.OBSERVE, True),
    }
)

_CONTEXTUAL_RECONCILE = frozenset(
    {"pump.rpm", "pool.raw_heater_id", "spa.raw_heater_id"}
)

_EXTERNAL_PUMP_RPM_TOLERANCE = 25.0


def _semantically_aligned(concept: str, intended: Any, observed: Any) -> bool:
    """Return whether current native truth is aligned with owned intent."""

    if concept != "pump.rpm":
        return intended == observed
    try:
        return abs(float(observed) - float(intended)) <= _EXTERNAL_PUMP_RPM_TOLERANCE
    except (TypeError, ValueError, OverflowError):
        return intended == observed


@dataclass(slots=True)
class ExternalNativeChangeMonitor:
    """Compare chronological native snapshots against one fresh baseline."""

    authority: PoolOSPhysicalCommandAuthority
    _baseline: dict[str, tuple[Any, str | None]] | None = field(
        default=None, init=False, repr=False
    )
    _schedule_baseline: dict[str, Mapping[str, Any]] | None = field(
        default=None, init=False, repr=False
    )
    _last_observed_at: datetime | None = field(default=None, init=False, repr=False)
    _latest_event: ExternalChangeEvent | None = field(default=None, init=False, repr=False)
    _event_count: int = field(default=0, init=False, repr=False)
    _correlated_count: int = field(default=0, init=False, repr=False)
    _regression_count: int = field(default=0, init=False, repr=False)
    _active_drift: dict[str, ExternalChangeEvent] = field(
        default_factory=dict, init=False, repr=False
    )

    def reset_baseline(self) -> None:
        """Forget comparison history at startup/reconnect/maintenance exit."""

        self._baseline = None
        self._schedule_baseline = None
        self._last_observed_at = None
        self._active_drift.clear()

    def process(
        self,
        native: NativeIntelliCenterObservationSnapshot,
        transport: NativeIntelliCenterTransportSnapshot,
        *,
        ownership: ExternalOwnershipContext = ExternalOwnershipContext(),
    ) -> ExternalChangeBatch:
        observed_at = native.generated_at
        current = {
            item.observation_id: (
                item.value,
                _native_object_id(item.source_id, transport.source_id),
            )
            for item in native.observations
        }
        maintenance = self.authority.maintenance_mode is not False
        if self._last_observed_at is not None:
            if observed_at < self._last_observed_at:
                self._regression_count += 1
                return ExternalChangeBatch(())
            if observed_at == self._last_observed_at:
                self._recompute_active_drift(
                    current,
                    ownership,
                    observed_at=observed_at,
                    maintenance=maintenance,
                )
                return ExternalChangeBatch(())
        schedules = _schedule_states(transport.raw_inventory)
        self._last_observed_at = observed_at
        if self._baseline is None or self._schedule_baseline is None:
            self._baseline = current
            self._schedule_baseline = schedules
            self.authority.replace_native_truth(_native_truth(current))
            self._recompute_active_drift(
                current,
                ownership,
                observed_at=observed_at,
                maintenance=maintenance,
            )
            return ExternalChangeBatch(())

        events: list[ExternalChangeEvent] = []
        correlations: list[NativeConsequenceAttribution] = []
        for concept in sorted(set(self._baseline).intersection(current)):
            previous, _previous_source = self._baseline[concept]
            value, source_id = current[concept]
            if previous == value:
                continue
            attribution = self.authority.correlate(
                concept=concept,
                native_object_id=source_id,
                value=value,
                observed_at=observed_at,
            )
            if attribution is not None:
                correlations.append(attribution)
                self._correlated_count += 1
                continue
            policy, notify = _policy_for(concept, ownership)
            if policy is None:
                continue
            intended = ownership.intended_values.get(concept)
            reconciliation = (
                policy is ExternalChangePolicy.RECONCILE
                and not _semantically_aligned(concept, intended, value)
            )
            action = _action(policy, maintenance=maintenance, reconciliation=reconciliation)
            event = ExternalChangeEvent(
                concept=concept,
                semantic_event_type=ExternalSemanticEventType.NATIVE_VALUE_CHANGED,
                native_object_id=source_id,
                previous_value=previous,
                new_value=value,
                observed_at=observed_at,
                external_policy=policy,
                action_taken=action,
                notification_recommended=(
                    notify
                    and not maintenance
                    and (policy is not ExternalChangePolicy.RECONCILE or reconciliation)
                ),
                reconciliation_required=reconciliation and not maintenance,
                intended_value=intended,
                maintenance_mode=maintenance,
                reason_code=(
                    "expected_maintenance_activity"
                    if maintenance
                    else "external_unattributed_native_change"
                ),
            )
            events.append(event)

        events.extend(
            _schedule_events(
                self._schedule_baseline,
                schedules,
                observed_at=observed_at,
                maintenance=maintenance,
            )
        )
        self._baseline = current
        self.authority.replace_native_truth(_native_truth(current))
        self._recompute_active_drift(
            current,
            ownership,
            observed_at=observed_at,
            maintenance=maintenance,
        )
        # Native inventory absence is not commissioned evidence that a known
        # schedule was deleted. Retain known IDs until an explicit tombstone or
        # a new value replaces them; this also prevents disappearance/reappear
        # churn from being mislabeled as schedule creation.
        retained_schedules = dict(self._schedule_baseline)
        retained_schedules.update(schedules)
        self._schedule_baseline = retained_schedules
        for event in events:
            self._latest_event = event
            self._event_count += 1
        return ExternalChangeBatch(tuple(events), tuple(correlations))

    def diagnostics(self) -> Mapping[str, Any]:
        latest = None if self._latest_event is None else dict(self._latest_event.as_event_data())
        return MappingProxyType(
            {
                "state": "BASELINE_PENDING" if self._baseline is None else (
                    "DRIFT" if self._active_drift else "MONITORING"
                ),
                "event_count": self._event_count,
                "correlated_poolos_consequence_count": self._correlated_count,
                "temporal_regression_count": self._regression_count,
                "active_drift_count": len(self._active_drift),
                "active_drift_concepts": sorted(self._active_drift)[:16],
                "active_drift_intended_values": {
                    concept: _bounded_value(event.intended_value)
                    for concept, event in sorted(self._active_drift.items())[:16]
                },
                "latest_event": latest,
                "history_retained": False,
                "authority": "none",
                "command_delivery_enabled": False,
            }
        )

    def clear_active_drift(self) -> None:
        """Clear current drift when PoolOS deliberately relinquishes control."""

        self._active_drift.clear()

    def current_concepts(self) -> frozenset[str]:
        """Return concepts in the last accepted authoritative native baseline."""

        return frozenset(() if self._baseline is None else self._baseline)

    def recompute_current_ownership(
        self,
        ownership: ExternalOwnershipContext,
    ) -> None:
        """Re-evaluate current drift without inventing a native transition."""

        if self._baseline is None or self._last_observed_at is None:
            self._active_drift.clear()
            return
        self._recompute_active_drift(
            self._baseline,
            ownership,
            observed_at=self._last_observed_at,
            maintenance=self.authority.maintenance_mode is not False,
        )

    def _recompute_active_drift(
        self,
        current: Mapping[str, tuple[Any, str | None]],
        ownership: ExternalOwnershipContext,
        *,
        observed_at: datetime,
        maintenance: bool,
    ) -> None:
        drift: dict[str, ExternalChangeEvent] = {}
        if not maintenance:
            for concept, intended in ownership.intended_values.items():
                if concept not in _CONTEXTUAL_RECONCILE or concept not in current:
                    continue
                value, source_id = current[concept]
                if _semantically_aligned(concept, intended, value):
                    continue
                drift[concept] = ExternalChangeEvent(
                    concept=concept,
                    semantic_event_type=ExternalSemanticEventType.NATIVE_VALUE_CHANGED,
                    native_object_id=source_id,
                    previous_value=value,
                    new_value=value,
                    observed_at=observed_at,
                    external_policy=ExternalChangePolicy.RECONCILE,
                    action_taken="reconciliation_required",
                    notification_recommended=True,
                    reconciliation_required=True,
                    intended_value=intended,
                    reason_code="current_contextual_drift",
                )
        self._active_drift = drift


def _policy_for(
    concept: str, ownership: ExternalOwnershipContext
) -> tuple[ExternalChangePolicy | None, bool]:
    if concept in _CONTEXTUAL_RECONCILE:
        if concept in ownership.intended_values:
            return ExternalChangePolicy.RECONCILE, True
        return ExternalChangePolicy.ACCEPT, False
    configured = _POLICIES.get(concept)
    return (None, False) if configured is None else configured


def _action(
    policy: ExternalChangePolicy, *, maintenance: bool, reconciliation: bool
) -> str:
    if maintenance:
        return "accepted_maintenance_activity"
    if policy is ExternalChangePolicy.ADOPT:
        return "adopted_native_value"
    if policy is ExternalChangePolicy.RECONCILE:
        return "reconciliation_required" if reconciliation else "already_aligned"
    if policy is ExternalChangePolicy.ACCEPT:
        return "accepted_native_value"
    return "observed_native_value"


def _schedule_states(
    inventory: tuple[NativeRawObject, ...],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for item in inventory:
        if item.object_type.upper() != "SCHED":
            continue
        values = {attribute.name.upper(): attribute.value for attribute in item.attributes}
        result[item.native_id] = MappingProxyType(
            {
                key: _bounded_value(values.get(key))
                for key in (
                    "CIRCUIT",
                    "DAYS",
                    "LOTMP",
                    "STATUS",
                    "TIME",
                    "TIMOUT",
                    "UPDATE",
                )
            }
        )
    return result


def _schedule_events(
    previous: Mapping[str, Mapping[str, Any]],
    current: Mapping[str, Mapping[str, Any]],
    *,
    observed_at: datetime,
    maintenance: bool,
) -> list[ExternalChangeEvent]:
    events: list[ExternalChangeEvent] = []
    for schedule_id in sorted(set(previous).union(current)):
        before = previous.get(schedule_id)
        after = current.get(schedule_id)
        if before == after:
            continue
        # Inventory absence alone is not commissioned deletion evidence.  The
        # transport can only classify deletion from the native tombstone/reset
        # signature observed on a known schedule object.
        if after is None:
            continue
        if before is None:
            semantic = ExternalSemanticEventType.SCHEDULE_CREATED
            changed = tuple(sorted(after.keys()))
        elif _is_schedule_tombstone(after):
            semantic = ExternalSemanticEventType.SCHEDULE_DELETED
            changed = tuple(
                sorted(key for key in set(before).union(after) if before.get(key) != after.get(key))
            )
        elif _is_schedule_tombstone(before):
            semantic = ExternalSemanticEventType.SCHEDULE_CREATED
            changed = tuple(
                sorted(key for key in set(before).union(after) if before.get(key) != after.get(key))
            )
        else:
            semantic = ExternalSemanticEventType.SCHEDULE_MODIFIED
            changed = tuple(
                sorted(key for key in set(before).union(after) if before.get(key) != after.get(key))
            )
        events.append(
            ExternalChangeEvent(
                concept="intellicenter.schedule",
                semantic_event_type=semantic,
                native_object_id=schedule_id,
                previous_value=before,
                new_value=after,
                observed_at=observed_at,
                external_policy=ExternalChangePolicy.OBSERVE,
                action_taken=(
                    "accepted_maintenance_activity"
                    if maintenance
                    else "observed_native_schedule_change"
                ),
                notification_recommended=not maintenance,
                reconciliation_required=False,
                maintenance_mode=maintenance,
                reason_code=(
                    "expected_maintenance_activity"
                    if maintenance
                    else "external_unattributed_native_change"
                ),
                changed_fields=changed,
            )
        )
    return events


def _is_schedule_tombstone(value: Mapping[str, Any]) -> bool:
    circuit = str(value.get("CIRCUIT") or "")
    return (
        circuit.startswith("X")
        and str(value.get("STATUS") or "").upper() == "OFF"
        and value.get("TIME") == "00:00"
        and value.get("TIMOUT") == "00:00"
        and value.get("UPDATE") == "00/00/00"
        and str(value.get("LOTMP") or "") == "78"
    )


def _native_truth(
    current: Mapping[str, tuple[Any, str | None]],
) -> dict[tuple[str, str], Any]:
    return {
        (concept, source_id): value
        for concept, (value, source_id) in current.items()
        if source_id is not None
    }


def _native_object_id(source_id: str | None, transport_source_id: str) -> str | None:
    if source_id is None:
        return None
    prefix = f"intellicenter_native:{transport_source_id}:"
    return source_id[len(prefix) :] if source_id.startswith(prefix) else source_id


def _bounded_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:256]
    if isinstance(value, Mapping):
        return {
            str(key)[:64]: _bounded_value(item)
            for key, item in list(sorted(value.items(), key=lambda pair: str(pair[0])))[:24]
        }
    if isinstance(value, (tuple, list)):
        return [_bounded_value(item) for item in value[:24]]
    return str(value)[:256]


__all__ = [
    "ExternalChangeBatch",
    "ExternalChangeEvent",
    "ExternalChangePolicy",
    "ExternalNativeChangeMonitor",
    "ExternalOwnershipContext",
    "ExternalSemanticEventType",
]
