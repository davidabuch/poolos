from datetime import datetime, timezone

from poolos.shadow_runtime import ShadowRuntime, ShadowRuntimeInput, observation_fingerprint

NOW = datetime(2026, 8, 5, 22, 0, tzinfo=timezone.utc)


def input_value(*, healthy: bool = True) -> ShadowRuntimeInput:
    fingerprint = observation_fingerprint(
        generated_at=NOW,
        facts={"pool.active": True, "pool.temperature": 84.0, "pump.rpm": 1800},
    )
    return ShadowRuntimeInput(
        evaluated_at=NOW,
        pool_temperature=84.0,
        pool_active=True,
        pump_rpm=1800,
        observation_healthy=healthy,
        observation_fingerprint=fingerprint,
    )


def test_shadow_runtime_runs_existing_orchestrator_without_commands() -> None:
    runtime = ShadowRuntime()
    result = runtime.evaluate(input_value())

    assert result.status == "completed"
    assert result.proposed_step_count == 0
    assert result.proposed_command_count == 0
    assert result.command_delivery_enabled is False
    assert len(runtime.flight_records) == 1


def test_unhealthy_observation_blocks_shadow_planning() -> None:
    result = ShadowRuntime().evaluate(input_value(healthy=False))

    assert result.status == "blocked_context"
    assert result.plan_id is None
    assert result.blocked_reasons == ("observation_unhealthy",)
    assert result.proposed_command_count == 0


def test_equivalent_input_has_stable_evaluation_identity() -> None:
    first = ShadowRuntime().evaluate(input_value())
    second = ShadowRuntime().evaluate(input_value())

    assert first.evaluation_id == second.evaluation_id
    assert first.observation_fingerprint == second.observation_fingerprint
    assert first.context_id == second.context_id


def test_diagnostics_omit_raw_observation_values_and_explanations() -> None:
    result = ShadowRuntime().evaluate(input_value())
    diagnostics = result.diagnostics()

    assert "pool_temperature" not in diagnostics
    assert "human_explanation" not in diagnostics
    assert "technical_explanation" not in diagnostics
    assert diagnostics["command_delivery_enabled"] is False
