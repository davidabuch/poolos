from datetime import UTC, datetime, timedelta

import pytest

from poolos.pump_operating_target import PumpOperatingTarget, PumpTargetUnit
from poolos.sanitation import (
    SanitationBody,
    SanitationController,
    SanitationLifecycle,
    SanitationObservation,
)


NOW = datetime(2026, 9, 27, 18, 0, tzinfo=UTC)


def observation(
    *,
    at: datetime = NOW,
    grid_on: bool | None = True,
    body: bool | None = True,
    other: bool | None = False,
    heat: str | None = "00000",
    rpm: float | None = 3200,
    gpm: float | None = None,
    manual_off: bool = False,
    manual_rpm: int | None = None,
    manual_gpm: int | None = None,
    usable: bool = True,
) -> SanitationObservation:
    return SanitationObservation(
        observed_at=at,
        grid_on=grid_on,
        target_body_active=body,
        other_body_active=other,
        heat_source_id=heat,
        pump_rpm=rpm,
        pump_gpm=gpm,
        body_evidence_usable=usable,
        thermal_evidence_usable=usable,
        pump_evidence_usable=usable,
        positive_manual_body_off=manual_off,
        positive_manual_pump_change_rpm=manual_rpm,
        positive_manual_pump_change_gpm=manual_gpm,
    )


def active_controller(
    body: SanitationBody = SanitationBody.HOT_TUB,
    duration: int = 4 * 60 * 60,
    target: PumpOperatingTarget | None = None,
) -> SanitationController:
    controller = SanitationController()
    controller.start(
        body=body,
        requested_at=NOW,
        target_rpm=3200,
        duration_seconds=duration,
        target=target,
    )
    return controller


def test_start_requires_heat_off_then_body_then_pump() -> None:
    controller = active_controller()

    heat = controller.observe(observation(heat="H0001", body=True, rpm=3000))
    assert heat.action is not None
    assert heat.action.kind.value == "heat_off"
    assert heat.action.requested_value == "00000"

    body = controller.observe(
        observation(at=NOW + timedelta(seconds=1), heat="00000", body=False, rpm=0)
    )
    assert body.action is not None
    assert body.action.kind.value == "body_on"

    pump = controller.observe(
        observation(at=NOW + timedelta(seconds=2), heat="00000", body=True, rpm=2600)
    )
    assert pump.action is not None
    assert pump.action.kind.value == "pump_set"
    assert pump.action.requested_value == 3200


def test_timer_counts_only_verified_sanitation_operation() -> None:
    controller = active_controller(duration=600)

    controller.observe(observation())
    active = controller.observe(observation(at=NOW + timedelta(minutes=2)))
    assert active.session is not None
    assert active.session.lifecycle is SanitationLifecycle.ACTIVE
    assert active.session.remaining_seconds == 480

    waiting = controller.observe(
        observation(
            at=NOW + timedelta(minutes=7),
            grid_on=None,
        )
    )
    assert waiting.session is not None
    assert waiting.session.remaining_seconds == 480

    controller.observe(
        observation(at=NOW + timedelta(minutes=8))
    )
    resumed = controller.observe(
        observation(at=NOW + timedelta(minutes=9))
    )
    assert resumed.session is not None
    assert resumed.session.remaining_seconds == 420


def test_grid_outage_pauses_and_same_session_resumes() -> None:
    controller = active_controller(duration=600)
    controller.observe(observation())
    before = controller.observe(observation(at=NOW + timedelta(minutes=2)))
    assert before.session is not None

    paused = controller.observe(
        observation(at=NOW + timedelta(minutes=3), grid_on=False)
    )
    assert paused.session is not None
    assert paused.session.lifecycle is SanitationLifecycle.PAUSED_OUTAGE
    remaining = paused.session.remaining_seconds

    controller.observe(
        observation(at=NOW + timedelta(hours=2))
    )
    after = controller.observe(
        observation(at=NOW + timedelta(hours=2, minutes=1))
    )
    assert after.session is not None
    assert after.session.session_id == before.session.session_id
    assert after.session.remaining_seconds == remaining - 60


def test_manual_body_off_cancels_and_never_restarts_body() -> None:
    controller = active_controller()
    controller.observe(observation())

    cancelling = controller.observe(
        observation(
            at=NOW + timedelta(seconds=1),
            body=False,
            rpm=0,
            manual_off=True,
        )
    )
    assert cancelling.session is None
    assert cancelling.action is None
    assert cancelling.reason_code == "sanitation_cancelled"


def test_manual_pump_override_pauses_and_exact_handback_resumes() -> None:
    controller = active_controller(duration=600)
    controller.observe(observation())

    yielded = controller.observe(
        observation(
            at=NOW + timedelta(minutes=1),
            rpm=2800,
            manual_rpm=2800,
        )
    )
    assert yielded.session is not None
    assert yielded.session.lifecycle is SanitationLifecycle.PAUSED_PUMP_OVERRIDE
    assert yielded.pump_owner == "external"
    remaining = yielded.session.remaining_seconds

    still_paused = controller.observe(
        observation(at=NOW + timedelta(minutes=4), rpm=2800)
    )
    assert still_paused.session is not None
    assert still_paused.session.remaining_seconds == remaining

    handed_back = controller.observe(
        observation(
            at=NOW + timedelta(minutes=5),
            rpm=3200,
            manual_rpm=3200,
        )
    )
    assert handed_back.session is not None
    assert handed_back.pump_owner == "poolos_sanitation"
    assert handed_back.session.remaining_seconds == remaining


def test_mutual_exclusion_rejects_second_body() -> None:
    controller = active_controller(SanitationBody.POOL)
    with pytest.raises(ValueError, match="another sanitation session"):
        controller.start(
            body=SanitationBody.HOT_TUB,
            requested_at=NOW + timedelta(seconds=1),
            target_rpm=3200,
            duration_seconds=600,
        )


def test_restart_restores_remaining_work_but_not_verified_time_continuity() -> None:
    controller = active_controller(duration=600)
    controller.observe(observation())
    active = controller.observe(observation(at=NOW + timedelta(minutes=2)))
    assert active.session is not None
    payload = active.session.persistent_dict()

    restarted = SanitationController()
    restored = restarted.restore(payload)
    assert restored.session is not None
    assert restored.session.lifecycle is SanitationLifecycle.STARTING
    assert restored.session.last_qualified_at is None
    assert restored.session.remaining_seconds == 480

    restarted.observe(observation(at=NOW + timedelta(hours=1)))
    later = restarted.observe(
        observation(at=NOW + timedelta(hours=1, minutes=1))
    )
    assert later.session is not None
    assert later.session.remaining_seconds == 420


def test_completion_requires_verified_body_off() -> None:
    controller = active_controller(duration=60)
    controller.observe(observation())
    completing = controller.observe(observation(at=NOW + timedelta(minutes=1)))
    assert completing.session is not None
    assert completing.session.lifecycle is SanitationLifecycle.COMPLETING
    assert completing.action is not None
    assert completing.action.kind.value == "body_off"

    repeated = controller.observe(
        observation(at=NOW + timedelta(minutes=1, seconds=1), body=True)
    )
    assert repeated.action is not None
    assert repeated.action.kind.value == "body_off"

    done = controller.observe(
        observation(
            at=NOW + timedelta(minutes=1, seconds=2),
            body=False,
            rpm=0,
        )
    )
    assert done.session is None
    assert done.reason_code == "sanitation_completed"


def test_gpm_sanitation_sets_and_verifies_flow_not_numeric_rpm() -> None:
    controller = active_controller(
        target=PumpOperatingTarget(PumpTargetUnit.GPM, 42)
    )

    needs_flow = controller.observe(
        observation(rpm=2800, gpm=30)
    )
    assert needs_flow.action is not None
    assert needs_flow.action.kind.value == "pump_set"
    assert needs_flow.action.requested_value == 42
    assert needs_flow.action.reason_code == "sanitation_set_pump_gpm"

    # A numerically matching RPM is not GPM convergence.
    still_needs_flow = controller.observe(
        observation(at=NOW + timedelta(seconds=1), rpm=42, gpm=30)
    )
    assert still_needs_flow.action is not None
    assert still_needs_flow.action.reason_code == "sanitation_set_pump_gpm"

    active = controller.observe(
        observation(at=NOW + timedelta(seconds=2), rpm=2400, gpm=43)
    )
    assert active.session is not None
    assert active.session.lifecycle is SanitationLifecycle.ACTIVE
    assert active.action is None


def test_gpm_sanitation_manual_override_and_handback_are_unit_scoped() -> None:
    controller = active_controller(
        duration=600,
        target=PumpOperatingTarget(PumpTargetUnit.GPM, 42),
    )
    controller.observe(observation(gpm=42))

    yielded = controller.observe(
        observation(
            at=NOW + timedelta(minutes=1),
            rpm=2500,
            gpm=50,
            manual_gpm=50,
        )
    )
    assert yielded.session is not None
    assert yielded.session.lifecycle is SanitationLifecycle.PAUSED_PUMP_OVERRIDE
    assert yielded.pump_owner == "external"

    handed_back = controller.observe(
        observation(
            at=NOW + timedelta(minutes=2),
            rpm=2450,
            gpm=42,
            manual_gpm=42,
        )
    )
    assert handed_back.session is not None
    assert handed_back.pump_owner == "poolos_sanitation"


def test_gpm_sanitation_persistence_preserves_unit_and_legacy_payloads_stay_rpm() -> None:
    controller = active_controller(
        duration=600,
        target=PumpOperatingTarget(PumpTargetUnit.GPM, 42),
    )
    assert controller.session is not None
    payload = controller.session.persistent_dict()

    restarted = SanitationController()
    restored = restarted.restore(payload)
    assert restored.session is not None
    assert restored.session.pump_target == PumpOperatingTarget(PumpTargetUnit.GPM, 42)

    legacy_payload = dict(payload)
    legacy_payload.pop("target_unit")
    legacy_payload.pop("target_gpm")
    legacy_payload["target_rpm"] = 3200
    legacy = SanitationController().restore(legacy_payload)
    assert legacy.session is not None
    assert legacy.session.pump_target == PumpOperatingTarget(PumpTargetUnit.RPM, 3200)
