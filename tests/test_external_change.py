from __future__ import annotations

from datetime import UTC, datetime, timedelta

from poolos.external_change import (
    ExternalChangePolicy,
    ExternalNativeChangeMonitor,
    ExternalOwnershipContext,
    ExternalSemanticEventType,
)
from poolos.intellicenter_readonly import (
    POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
    NativeIntelliCenterObservationSnapshot,
    NativeIntelliCenterReadAdapter,
    NativeIntelliCenterStatus,
    NativeIntelliCenterTransportSnapshot,
    NativeRawAttribute,
    NativeRawObject,
)
from poolos.observations import ObservationQuality, PoolObservation
from poolos.physical_command_authority import (
    ExpectedNativeConsequence,
    PhysicalCommandRequest,
    PhysicalRequestSource,
    PoolOSPhysicalCommandAuthority,
)


NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def authority(*, maintenance: bool = False) -> PoolOSPhysicalCommandAuthority:
    result = PoolOSPhysicalCommandAuthority()
    result.resolve_maintenance(maintenance)
    result.set_controller_mode("auto")
    return result


def snapshot(
    at: datetime,
    values: dict[str, tuple[object, str]],
    *,
    schedules: tuple[NativeRawObject, ...] = (),
) -> tuple[NativeIntelliCenterObservationSnapshot, NativeIntelliCenterTransportSnapshot]:
    native = NativeIntelliCenterObservationSnapshot(
        generated_at=at,
        status=NativeIntelliCenterStatus.AVAILABLE,
        source_id="native",
        observations=tuple(
            PoolObservation(
                concept,
                value,
                observed_at=at,
                source_id=source_id,
                quality=ObservationQuality.GOOD,
            )
            for concept, (value, source_id) in values.items()
        ),
        missing_concepts=(),
    )
    transport = NativeIntelliCenterTransportSnapshot(
        source_id="native",
        observed_at=at,
        connected=True,
        temperature_unit="°F",
        raw_inventory=schedules,
    )
    return native, transport


def schedule(at: datetime, schedule_id: str = "SCH03", **values: str) -> NativeRawObject:
    return NativeRawObject(
        native_id=schedule_id,
        object_type="SCHED",
        subtype=None,
        name=schedule_id,
        parent_id=None,
        observed_at=at,
        attributes=tuple(NativeRawAttribute(key, value) for key, value in values.items()),
    )


def process(
    monitor: ExternalNativeChangeMonitor,
    at: datetime,
    values: dict[str, tuple[object, str]],
    *,
    ownership: ExternalOwnershipContext = ExternalOwnershipContext(),
    schedules: tuple[NativeRawObject, ...] = (),
):
    native, transport = snapshot(at, values, schedules=schedules)
    return monitor.process(native, transport, ownership=ownership)


def test_initial_duplicate_regressive_and_reset_snapshots_are_baselines() -> None:
    monitor = ExternalNativeChangeMonitor(authority())
    values = {"pool.active": (False, "B1101")}
    assert process(monitor, NOW, values).events == ()
    assert process(monitor, NOW, values).events == ()
    assert process(monitor, NOW - timedelta(seconds=1), values).events == ()
    assert monitor.diagnostics()["temporal_regression_count"] == 1
    monitor.reset_baseline()
    assert process(monitor, NOW + timedelta(seconds=1), {"pool.active": (True, "B1101")}).events == ()


def test_product_policy_distinguishes_adopt_accept_observe_and_notifications() -> None:
    monitor = ExternalNativeChangeMonitor(authority())
    before = {
        "pool.active": (True, "B1101"),
        "spa.active": (False, "B1202"),
        "pool.target_temperature": (86.0, "B1101"),
        "spa.target_temperature": (98.0, "B1202"),
        "intellichlor.pool_output_percent": (52, "CHR01"),
        "pool_light.active": (False, "C0002"),
        "freeze.active": (False, "FRE01"),
    }
    process(monitor, NOW, before)
    after = {
        "pool.active": (False, "B1101"),
        "spa.active": (True, "B1202"),
        "pool.target_temperature": (88.0, "B1101"),
        "spa.target_temperature": (99.0, "B1202"),
        "intellichlor.pool_output_percent": (65, "CHR01"),
        "pool_light.active": (True, "C0002"),
        "freeze.active": (True, "FRE01"),
    }
    events = {event.concept: event for event in process(monitor, NOW + timedelta(seconds=1), after).events}
    assert events["pool.active"].external_policy is ExternalChangePolicy.ACCEPT
    assert events["pool.active"].notification_recommended
    assert not events["spa.active"].notification_recommended
    assert events["pool.target_temperature"].external_policy is ExternalChangePolicy.ADOPT
    assert events["pool.target_temperature"].action_taken == "adopted_native_value"
    assert not events["spa.target_temperature"].notification_recommended
    assert events["intellichlor.pool_output_percent"].notification_recommended
    assert not events["pool_light.active"].notification_recommended
    assert events["freeze.active"].external_policy is ExternalChangePolicy.OBSERVE


def test_contextual_rpm_and_heater_ownership_create_current_drift_only_when_owned() -> None:
    monitor = ExternalNativeChangeMonitor(authority())
    before = {
        "pump.rpm": (2900.0, "PMP01"),
        "pool.raw_heater_id": ("H0002", "B1101"),
    }
    process(monitor, NOW, before)
    owned = ExternalOwnershipContext(
        {"pump.rpm": 2900, "pool.raw_heater_id": "H0002"}
    )
    batch = process(
        monitor,
        NOW + timedelta(seconds=1),
        {"pump.rpm": (2600.0, "PMP01"), "pool.raw_heater_id": ("H0001", "B1101")},
        ownership=owned,
    )
    assert all(event.reconciliation_required for event in batch.events)
    assert monitor.diagnostics()["active_drift_count"] == 2

    unowned = ExternalNativeChangeMonitor(authority())
    process(unowned, NOW, before)
    batch = process(
        unowned,
        NOW + timedelta(seconds=1),
        {"pump.rpm": (2600.0, "PMP01"), "pool.raw_heater_id": ("H0001", "B1101")},
    )
    assert all(not event.reconciliation_required for event in batch.events)
    assert all(not event.notification_recommended for event in batch.events)


def test_pump_rpm_semantic_tolerance_is_shared_by_events_and_current_drift() -> None:
    owned = ExternalOwnershipContext({"pump.rpm": 2900})

    for observed, expected_drift in (
        (2900.0, False),
        (2904.0, False),
        (2925.0, False),
        (2926.0, True),
    ):
        monitor = ExternalNativeChangeMonitor(authority())
        process(
            monitor,
            NOW,
            {"pump.rpm": (2900.0, "PMP01")},
            ownership=owned,
        )
        batch = process(
            monitor,
            NOW + timedelta(seconds=1),
            {"pump.rpm": (observed, "PMP01")},
            ownership=owned,
        )

        diagnostics = monitor.diagnostics()
        assert (diagnostics["active_drift_count"] == 1) is expected_drift

        if observed == 2900.0:
            assert batch.events == ()
            continue

        assert len(batch.events) == 1
        event = batch.events[0]
        assert event.concept == "pump.rpm"
        assert event.reconciliation_required is expected_drift
        assert event.notification_recommended is expected_drift
        assert event.action_taken == (
            "reconciliation_required" if expected_drift else "already_aligned"
        )


def test_real_external_pump_rpm_change_still_requires_reconciliation() -> None:
    monitor = ExternalNativeChangeMonitor(authority())
    owned = ExternalOwnershipContext({"pump.rpm": 2900})
    process(
        monitor,
        NOW,
        {"pump.rpm": (2900.0, "PMP01")},
        ownership=owned,
    )

    batch = process(
        monitor,
        NOW + timedelta(seconds=1),
        {"pump.rpm": (2600.0, "PMP01")},
        ownership=owned,
    )

    assert len(batch.events) == 1
    event = batch.events[0]
    assert event.reconciliation_required
    assert event.notification_recommended
    assert event.action_taken == "reconciliation_required"
    assert monitor.diagnostics()["active_drift_concepts"] == ["pump.rpm"]


def test_heat_source_drift_remains_exact() -> None:
    monitor = ExternalNativeChangeMonitor(authority())
    owned = ExternalOwnershipContext({"pool.raw_heater_id": "H0002"})
    process(
        monitor,
        NOW,
        {"pool.raw_heater_id": ("H0002", "B1101")},
        ownership=owned,
    )

    batch = process(
        monitor,
        NOW + timedelta(seconds=1),
        {"pool.raw_heater_id": ("H0001", "B1101")},
        ownership=owned,
    )

    assert len(batch.events) == 1
    assert batch.events[0].reconciliation_required
    assert batch.events[0].notification_recommended
    assert monitor.diagnostics()["active_drift_concepts"] == ["pool.raw_heater_id"]


def test_nonnumeric_pump_rpm_fails_safe_as_drift() -> None:
    monitor = ExternalNativeChangeMonitor(authority())
    owned = ExternalOwnershipContext({"pump.rpm": 2900})
    process(
        monitor,
        NOW,
        {"pump.rpm": (2900.0, "PMP01")},
        ownership=owned,
    )

    batch = process(
        monitor,
        NOW + timedelta(seconds=1),
        {"pump.rpm": ("not-a-number", "PMP01")},
        ownership=owned,
    )

    assert len(batch.events) == 1
    assert batch.events[0].reconciliation_required
    assert batch.events[0].notification_recommended
    assert monitor.diagnostics()["active_drift_concepts"] == ["pump.rpm"]


def test_current_drift_recomputes_when_ownership_or_intention_changes() -> None:
    monitor = ExternalNativeChangeMonitor(authority())
    values = {
        "pump.rpm": (2600.0, "PMP01"),
        "pool.raw_heater_id": ("H0001", "B1101"),
        "spa.raw_heater_id": ("H0001", "B1202"),
    }
    owned = ExternalOwnershipContext(
        {
            "pump.rpm": 2900,
            "pool.raw_heater_id": "H0002",
            "spa.raw_heater_id": "H0002",
        }
    )
    process(monitor, NOW, values, ownership=owned)
    assert monitor.diagnostics()["active_drift_count"] == 3

    process(
        monitor,
        NOW + timedelta(seconds=1),
        values,
        ownership=ExternalOwnershipContext(),
    )
    assert monitor.diagnostics()["active_drift_count"] == 0

    changed_intent = ExternalOwnershipContext(
        {
            "pump.rpm": 2600,
            "pool.raw_heater_id": "H0001",
            "spa.raw_heater_id": "H0002",
        }
    )
    process(
        monitor,
        NOW + timedelta(seconds=2),
        values,
        ownership=changed_intent,
    )
    diagnostics = monitor.diagnostics()
    assert diagnostics["active_drift_concepts"] == ["spa.raw_heater_id"]
    assert diagnostics["active_drift_intended_values"] == {
        "spa.raw_heater_id": "H0002"
    }

    process(
        monitor,
        NOW + timedelta(seconds=3),
        values,
        ownership=owned,
    )
    assert monitor.diagnostics()["active_drift_count"] == 3


def test_maintenance_and_reconnect_clear_current_drift() -> None:
    command_authority = authority()
    monitor = ExternalNativeChangeMonitor(command_authority)
    owned = ExternalOwnershipContext({"pump.rpm": 2900})
    values = {"pump.rpm": (2600.0, "PMP01")}
    process(monitor, NOW, values, ownership=owned)
    assert monitor.diagnostics()["active_drift_count"] == 1

    command_authority.resolve_maintenance(True)
    process(monitor, NOW + timedelta(seconds=1), values, ownership=owned)
    assert monitor.diagnostics()["active_drift_count"] == 0

    monitor.reset_baseline()
    assert monitor.diagnostics()["active_drift_count"] == 0


def test_correlated_poolos_consequence_is_consumed_not_reported_external() -> None:
    command_authority = authority()
    monitor = ExternalNativeChangeMonitor(command_authority)
    process(monitor, NOW, {"pool.target_temperature": (86.0, "B1101")})
    request = PhysicalCommandRequest(
        "heating_setpoint", "B1101", PhysicalRequestSource.MANUAL, 88
    )
    expectation = command_authority.reserve(
        request,
        ExpectedNativeConsequence("pool.target_temperature", "B1101", 88.0),
        now=NOW,
    )
    command_authority.mark_dispatch_started(expectation)
    batch = process(
        monitor,
        NOW + timedelta(seconds=1),
        {"pool.target_temperature": (88.0, "B1101")},
    )
    assert batch.events == ()
    assert len(batch.correlated_consequences) == 1
    assert monitor.diagnostics()["correlated_poolos_consequence_count"] == 1


def test_no_op_expectation_cannot_hide_later_unrelated_excursion_and_return() -> None:
    command_authority = authority()
    monitor = ExternalNativeChangeMonitor(command_authority)
    process(monitor, NOW, {"pool.target_temperature": (88.0, "B1101")})
    request = PhysicalCommandRequest(
        "heating_setpoint", "B1101", PhysicalRequestSource.MANUAL, 88
    )
    assert command_authority.reserve(
        request,
        ExpectedNativeConsequence("pool.target_temperature", "B1101", 88.0),
        now=NOW,
    ) is None

    away = process(
        monitor,
        NOW + timedelta(seconds=1),
        {"pool.target_temperature": (87.0, "B1101")},
    )
    returned = process(
        monitor,
        NOW + timedelta(seconds=2),
        {"pool.target_temperature": (88.0, "B1101")},
    )
    assert len(away.events) == 1
    assert len(returned.events) == 1
    assert returned.correlated_consequences == ()


def test_correlation_uses_raw_native_identity_from_canonical_provenance() -> None:
    command_authority = authority()
    monitor = ExternalNativeChangeMonitor(command_authority)

    def configured_speed(at: datetime, rpm: int):
        transport = NativeIntelliCenterTransportSnapshot(
            source_id="native",
            observed_at=at,
            connected=True,
            temperature_unit="°F",
            raw_inventory=(
                NativeRawObject(
                    native_id="p0102",
                    object_type="PMPCIRC",
                    subtype=None,
                    name="Pool",
                    parent_id="PMP01",
                    observed_at=at,
                    attributes=(NativeRawAttribute("SPEED", str(rpm)),),
                ),
            ),
        )
        native = NativeIntelliCenterReadAdapter().map_snapshot(
            transport,
            generated_at=at,
        )
        return native, transport

    native, transport = configured_speed(NOW, 2600)
    monitor.process(native, transport)
    expectation = command_authority.reserve(
        PhysicalCommandRequest(
            "pump_circuit_speed",
            "p0102",
            PhysicalRequestSource.MANUAL,
            2900,
        ),
        ExpectedNativeConsequence(
            POOL_PUMP_CIRCUIT_CONFIGURED_SPEED_CONCEPT,
            "p0102",
            2900.0,
        ),
        now=NOW,
    )
    assert expectation is not None
    command_authority.mark_dispatch_started(expectation)

    native, transport = configured_speed(NOW + timedelta(seconds=1), 2900)
    batch = monitor.process(native, transport)
    assert len(batch.correlated_consequences) == 1
    assert batch.events == ()


def test_maintenance_records_changes_without_warning_or_drift_then_exit_rebaselines() -> None:
    command_authority = authority(maintenance=True)
    monitor = ExternalNativeChangeMonitor(command_authority)
    process(monitor, NOW, {"pool.target_temperature": (86.0, "B1101")})
    event = process(
        monitor,
        NOW + timedelta(seconds=1),
        {"pool.target_temperature": (88.0, "B1101")},
    ).events[0]
    assert event.maintenance_mode
    assert not event.notification_recommended
    assert event.action_taken == "accepted_maintenance_activity"
    command_authority.resolve_maintenance(False)
    monitor.reset_baseline()
    assert process(
        monitor,
        NOW + timedelta(seconds=2),
        {"pool.target_temperature": (88.0, "B1101")},
    ).events == ()


def test_known_schedule_modification_and_tombstone_are_single_semantic_events() -> None:
    monitor = ExternalNativeChangeMonitor(authority())
    active = schedule(
        NOW,
        CIRCUIT="C0006",
        LOTMP="47",
        STATUS="ON",
        TIME="23:00",
        TIMOUT="23:11",
        UPDATE="09/01/26",
    )
    process(monitor, NOW, {}, schedules=(active,))
    modified = schedule(
        NOW + timedelta(seconds=1),
        CIRCUIT="C0006",
        LOTMP="47",
        STATUS="ON",
        TIME="23:00",
        TIMOUT="23:15",
        UPDATE="09/01/26",
    )
    modification = process(
        monitor, NOW + timedelta(seconds=1), {}, schedules=(modified,)
    ).events
    assert len(modification) == 1
    assert modification[0].semantic_event_type is ExternalSemanticEventType.SCHEDULE_MODIFIED
    assert modification[0].changed_fields == ("TIMOUT",)

    tombstone = schedule(
        NOW + timedelta(seconds=2),
        CIRCUIT="X0056",
        LOTMP="78",
        STATUS="OFF",
        TIME="00:00",
        TIMOUT="00:00",
        UPDATE="00/00/00",
    )
    deletion = process(
        monitor, NOW + timedelta(seconds=2), {}, schedules=(tombstone,)
    ).events
    assert len(deletion) == 1
    assert deletion[0].semantic_event_type is ExternalSemanticEventType.SCHEDULE_DELETED
    assert deletion[0].notification_recommended


def test_schedule_absence_alone_is_not_classified_as_deletion() -> None:
    monitor = ExternalNativeChangeMonitor(authority())
    active = schedule(
        NOW,
        CIRCUIT="C0006",
        STATUS="ON",
        TIME="23:00",
        TIMOUT="23:11",
        UPDATE="09/01/26",
    )
    process(monitor, NOW, {}, schedules=(active,))

    assert process(monitor, NOW + timedelta(seconds=1), {}, schedules=()).events == ()
    assert process(
        monitor, NOW + timedelta(seconds=2), {}, schedules=(active,)
    ).events == ()


def test_known_tombstone_slot_reuse_is_classified_as_creation() -> None:
    monitor = ExternalNativeChangeMonitor(authority())
    tombstone = schedule(
        NOW,
        CIRCUIT="X0056",
        LOTMP="78",
        STATUS="OFF",
        TIME="00:00",
        TIMOUT="00:00",
        UPDATE="00/00/00",
    )
    process(monitor, NOW, {}, schedules=(tombstone,))
    reused = schedule(
        NOW + timedelta(seconds=1),
        CIRCUIT="C0006",
        STATUS="ON",
        TIME="23:00",
        TIMOUT="23:11",
        UPDATE="09/01/26",
    )

    events = process(
        monitor, NOW + timedelta(seconds=1), {}, schedules=(reused,)
    ).events
    assert len(events) == 1
    assert events[0].semantic_event_type is ExternalSemanticEventType.SCHEDULE_CREATED


def test_schedule_tombstone_requires_the_full_commissioned_reset_signature() -> None:
    cases = (
        schedule(
            NOW + timedelta(seconds=1),
            CIRCUIT="C0006",
            LOTMP="78",
            STATUS="OFF",
            TIME="00:00",
            TIMOUT="00:00",
            UPDATE="00/00/00",
        ),
        schedule(
            NOW + timedelta(seconds=1),
            CIRCUIT="X0056",
            LOTMP="78",
            STATUS="OFF",
            TIME="00:00",
            TIMOUT="00:00",
            UPDATE="09/01/26",
        ),
        schedule(
            NOW + timedelta(seconds=1),
            CIRCUIT="X0056",
            LOTMP="70",
            STATUS="OFF",
            TIME="00:00",
            TIMOUT="00:00",
            UPDATE="00/00/00",
        ),
    )
    for index, candidate in enumerate(cases):
        monitor = ExternalNativeChangeMonitor(authority())
        active = schedule(
            NOW,
            CIRCUIT="C0006",
            LOTMP="47",
            STATUS="OFF",
            TIME="23:00",
            TIMOUT="23:11",
            UPDATE="09/01/26",
        )
        process(monitor, NOW, {}, schedules=(active,))
        events = process(
            monitor,
            NOW + timedelta(seconds=1),
            {},
            schedules=(candidate,),
        ).events
        assert len(events) == 1, index
        assert events[0].semantic_event_type is ExternalSemanticEventType.SCHEDULE_MODIFIED


def test_diagnostics_are_bounded_to_latest_event_and_counts() -> None:
    monitor = ExternalNativeChangeMonitor(authority())
    process(monitor, NOW, {"pool.active": (False, "B1101")})
    for offset in range(1, 100):
        process(
            monitor,
            NOW + timedelta(seconds=offset),
            {"pool.active": (bool(offset % 2), "B1101")},
        )
    diagnostics = monitor.diagnostics()
    assert diagnostics["event_count"] == 99
    assert diagnostics["history_retained"] is False
    assert isinstance(diagnostics["latest_event"], dict)
