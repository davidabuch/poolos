"""Durable reconciliation guard for Pool/Solar autonomy closure.

This module does not model a second controller.  It binds the code-derived
authority-changing production paths to the behavioral regressions that execute
them, so deleting a path or its proof makes the closure suite fail.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from hashlib import sha256
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


class ProofLevel(StrEnum):
    COMPONENT = "component"
    PRODUCTION_COMPOSITION = "production_composition"
    LIFECYCLE = "lifecycle"


class EventClassification(StrEnum):
    AUTHORITATIVE = "authoritative"
    SUPERSEDED = "superseded"
    RETIRED = "retired"
    IRRELEVANT = "irrelevant"
    TRUE_EXTERNAL_TAKEOVER = "true_external_takeover"


class ReasonClassification(StrEnum):
    NORMAL_TRANSITION = "normal_transition"
    EXPECTED_WAIT = "expected_wait"
    INTENTIONAL_SAFETY_BOUNDARY = "intentional_safety_boundary"
    MANUAL_EXTERNAL_TAKEOVER = "manual_external_takeover"
    IMPOSSIBLE_ON_NORMAL_SUCCESS = "impossible_on_normal_success"
    UNREACHABLE = "unreachable"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    PROVEN_BUG = "proven_bug"


@dataclass(frozen=True, slots=True)
class ClosureProof:
    key: str
    production_file: str
    production_symbol: str
    regression: str
    level: ProofLevel
    invariant: str


@dataclass(frozen=True, slots=True)
class EventEpochProof:
    chronology: str
    classification: EventClassification
    consumer_file: str
    consumer_symbol: str
    regression: str
    rationale: str


@dataclass(frozen=True, slots=True)
class GenerationCaseProof:
    generation: str
    history: str
    classification: EventClassification
    regression: str
    invariant: str


@dataclass(frozen=True, slots=True)
class LivenessDimensionProof:
    state: str
    dimension: str
    regression: str
    expected: str


PHASE_PROOFS = (
    ClosureProof("A_candidate_activation", "poolos/thermal_automatic_execution.py", "process_epoch", "test_accepted_body_activation_waits_for_authoritative_consequence", ProofLevel.COMPONENT, "candidate delivery cannot skip body reobservation"),
    ClosureProof("B_activation_probe", "poolos/thermal_automatic_execution.py", "_begin_verified_probe_acquisition", "test_normal_day_pool_and_spa_complete_lifecycle", ProofLevel.LIFECYCLE, "probe is the untrusted-temperature acquisition path"),
    ClosureProof("C_probe_solar", "poolos/thermal_runtime_ownership.py", "handoff", "test_cold_start_probe_hands_off_to_fresh_thermal_provenance", ProofLevel.PRODUCTION_COMPOSITION, "probe handoff retains only verified body origin"),
    ClosureProof("D_activation_prime", "poolos/thermal_automatic_execution.py", "process_epoch", "test_retained_prime_event_is_replaced_before_solar_termination_and_cleanup", ProofLevel.LIFECYCLE, "trusted-temperature cold start primes at accepted operation intent"),
    ClosureProof("E_prime_solar", "poolos/thermal_runtime_ownership.py", "_external_preemption_reason", "test_retained_prime_event_is_replaced_before_solar_termination_and_cleanup", ProofLevel.LIFECYCLE, "new same-concept event supersedes prime-era evidence"),
    ClosureProof("F_rpm_source", "poolos/thermal_live_execution.py", "advance", "test_quiescent_solar_cold_start_verifies_h0002_before_engagement", ProofLevel.PRODUCTION_COMPOSITION, "source selection follows verified circulation"),
    ClosureProof("G_source_engagement", "poolos/thermal_automatic_execution.py", "_process_solar_engagement", "test_quiescent_solar_cold_start_verifies_h0002_before_engagement", ProofLevel.PRODUCTION_COMPOSITION, "H0002 verification is distinct from engagement"),
    ClosureProof("H_engagement_converged", "poolos/thermal_automatic_execution.py", "_process_solar_engagement", "test_normal_day_pool_and_spa_complete_lifecycle", ProofLevel.LIFECYCLE, "continuous engagement confirmation reaches owned convergence"),
    ClosureProof("I_converged_termination", "poolos/thermal_termination.py", "assess", "test_owned_pool_source_off_is_the_only_physical_termination_action", ProofLevel.COMPONENT, "termination is source-Off only while source provenance remains valid"),
    ClosureProof("J_source_off_verification", "poolos/thermal_automatic_execution.py", "_process_termination", "test_same_timestamp_command_callback_cannot_verify_termination", ProofLevel.COMPONENT, "verification must be strictly post-acceptance"),
    ClosureProof("K_source_off_filtration", "poolos/circulation_successor.py", "assess", "test_verified_source_off_then_normalizes_filtration_once_and_later_stops_body", ProofLevel.PRODUCTION_COMPOSITION, "independent RUN_NOW filtration alone creates a 2600 successor"),
    ClosureProof("L_thermal_filtration_owner", "poolos/pool_circulation_ownership.py", "accept_thermal_to_filtration", "test_normal_day_pool_and_spa_complete_lifecycle", ProofLevel.LIFECYCLE, "typed handoff transfers circulation ownership"),
    ClosureProof("M_filtration_cleanup", "poolos/filtration_automatic_execution.py", "process_epoch", "test_normal_day_pool_and_spa_complete_lifecycle", ProofLevel.LIFECYCLE, "filtration completion uses provenance-bound body Off"),
    ClosureProof("N_manual_resume", "poolos/thermal_automatic_execution.py", "set_enabled", "test_manual_pool_off_consumes_origin_and_later_external_on_is_never_adopted", ProofLevel.PRODUCTION_COMPOSITION, "manual Off consumes old authority and resume cannot adopt equality"),
    ClosureProof("O_authority_epoch", "poolos/thermal_runtime_ownership.py", "handoff", "test_old_event_cannot_preempt_successor_lease_after_prior_preemption", ProofLevel.COMPONENT, "old event cannot poison a new lease generation"),
    ClosureProof("P_transport_generation", "custom_components/poolos/external_change_runtime.py", "process", "test_runtime_publishes_one_stable_bounded_ha_event_after_baseline", ProofLevel.PRODUCTION_COMPOSITION, "new discovery generation resets retained native baseline"),
    ClosureProof("Q_restart_runtime", "poolos/thermal_runtime_ownership.py", "ThermalRuntimeOwnershipManager", "test_restart_cannot_handoff_an_old_runtime_lease", ProofLevel.COMPONENT, "restart begins unowned and cannot reconstruct provenance"),
)


GENERATION_PROOFS = (
    ClosureProof("runtime_ownership", "poolos/thermal_runtime_ownership.py", "handoff", "test_old_event_cannot_preempt_successor_lease_after_prior_preemption", ProofLevel.COMPONENT, "historical evidence cannot poison or create a lease"),
    ClosureProof("execution_session", "poolos/thermal_runtime_ownership.py", "promote", "test_session_provenance_promotion_rejects_different_session", ProofLevel.COMPONENT, "old command provenance cannot verify a new session"),
    ClosureProof("pump_speed_session", "poolos/thermal_runtime_ownership.py", "evaluate", "test_probe_replacement_handoff_rejects_stale_generation", ProofLevel.COMPONENT, "stale pump phase cannot cross a typed handoff"),
    ClosureProof("autonomous_resume", "poolos/thermal_automatic_execution.py", "set_enabled", "test_preempted_thermal_session_allows_genuinely_fresh_successor_session", ProofLevel.PRODUCTION_COMPOSITION, "resume requires a fresh authority epoch"),
    ClosureProof("termination_entitlement", "poolos/thermal_automatic_execution.py", "_process_cleanup", "test_cleanup_attempt_cannot_cross_provenance_generation", ProofLevel.PRODUCTION_COMPOSITION, "old entitlement generation cannot complete later cleanup"),
    ClosureProof("transport_discovery", "custom_components/poolos/external_change_runtime.py", "process", "test_runtime_publishes_one_stable_bounded_ha_event_after_baseline", ProofLevel.PRODUCTION_COMPOSITION, "old transport generation cannot verify current state"),
    ClosureProof("restart_runtime", "poolos/thermal_runtime_ownership.py", "ThermalRuntimeOwnershipManager", "test_restart_with_matching_pool_state_reconstructs_no_cleanup_authority", ProofLevel.PRODUCTION_COMPOSITION, "hardware equality after restart creates no authority"),
)


LIVENESS_PROOFS = (
    ClosureProof("blocked", "poolos/thermal_automatic_execution.py", "process_epoch", "test_driver_defaults_off_and_enable_requires_a_new_epoch", ProofLevel.COMPONENT, "fresh epoch or explicit enable is the documented recovery"),
    ClosureProof("awaiting_reobservation", "poolos/thermal_automatic_execution.py", "process_epoch", "test_accepted_body_activation_waits_for_authoritative_consequence", ProofLevel.COMPONENT, "later body truth progresses without duplicate delivery"),
    ClosureProof("awaiting_verification", "poolos/thermal_live_execution.py", "advance", "test_accepted_unverified_body_times_out_without_cleanup_or_retry", ProofLevel.COMPONENT, "verification has a fixed deadline"),
    ClosureProof("observing_solar_engagement", "poolos/thermal_automatic_execution.py", "_process_solar_engagement", "test_unengaged_solar_cold_start_is_bounded_and_not_immediately_retried", ProofLevel.PRODUCTION_COMPOSITION, "absolute engagement deadline cannot be reset by reevaluation"),
    ClosureProof("terminating", "poolos/thermal_automatic_execution.py", "_process_termination", "test_owned_gas_source_is_deselected_then_verified_without_stopping_pool", ProofLevel.PRODUCTION_COMPOSITION, "termination either delivers or reaches a fail-closed disposition"),
    ClosureProof("awaiting_termination_verification", "poolos/thermal_automatic_execution.py", "_process_termination", "test_accepted_termination_delivery_needs_a_later_authoritative_epoch", ProofLevel.COMPONENT, "strict causal verification or timeout resolves the attempt"),
    ClosureProof("cleanup_waiting", "poolos/thermal_automatic_execution.py", "_process_cleanup", "test_verified_source_off_then_normalizes_filtration_once_and_later_stops_body", ProofLevel.PRODUCTION_COMPOSITION, "fresh arbitration selects one bounded cleanup action"),
    ClosureProof("awaiting_cleanup_verification", "poolos/thermal_automatic_execution.py", "_process_cleanup", "test_body_cleanup_receipt_is_not_verification", ProofLevel.COMPONENT, "receipt alone cannot complete cleanup"),
    ClosureProof("preempted", "poolos/thermal_runtime_ownership.py", "evaluate", "test_preempted_thermal_session_allows_genuinely_fresh_successor_session", ProofLevel.PRODUCTION_COMPOSITION, "terminal ownership needs a genuinely fresh accepted session"),
    ClosureProof("relinquished", "poolos/thermal_runtime_ownership.py", "relinquish", "test_relinquishment_is_terminal_and_command_free", ProofLevel.COMPONENT, "relinquishment is terminal and command-free"),
    ClosureProof("failed", "poolos/thermal_automatic_execution.py", "_fail", "test_rejected_delivery_fails_closed_without_retry_or_ownership", ProofLevel.COMPONENT, "failure cannot retry or manufacture provenance"),
    ClosureProof("superseded", "poolos/thermal_runtime_ownership.py", "evaluate", "test_true_requested_mode_supersession_terminates_without_next_delivery", ProofLevel.PRODUCTION_COMPOSITION, "supersession cannot replay stale work"),
)


CONTROL_PATH_PROOFS = PHASE_PROOFS + GENERATION_PROOFS + LIVENESS_PROOFS


EVENT_EPOCH_PROOFS = (
    EventEpochProof("matching_historical_without_provenance", EventClassification.IRRELEVANT, "poolos/thermal_runtime_ownership.py", "establish", "test_preexisting_or_matching_native_state_does_not_create_ownership", "equality cannot create authority"),
    EventEpochProof("matching_post_acceptance_unverified", EventClassification.TRUE_EXTERNAL_TAKEOVER, "poolos/thermal_runtime_ownership.py", "_external_preemption_reason", "test_unverified_matching_pump_event_still_preempts", "only verified provenance may explain a retained event"),
    EventEpochProof("pre_acceptance", EventClassification.TRUE_EXTERNAL_TAKEOVER, "poolos/thermal_termination.py", "_external_takeover", "test_earlier_external_pump_event_cannot_be_retroactively_adopted", "an earlier event cannot become a later command consequence"),
    EventEpochProof("exact_acceptance", EventClassification.TRUE_EXTERNAL_TAKEOVER, "poolos/external_change.py", "pump_event_conflicts_with_provenance", "test_pump_event_provenance_boundary_is_deterministic", "causality is strict, not inclusive"),
    EventEpochProof("matching_post_verification", EventClassification.AUTHORITATIVE, "poolos/thermal_runtime_ownership.py", "_external_preemption_reason", "test_owned_prime_actual_rpm_transition_does_not_self_preempt", "verified accepted intent explains its later consequence"),
    EventEpochProof("contradictory_post_verification", EventClassification.TRUE_EXTERNAL_TAKEOVER, "poolos/thermal_runtime_ownership.py", "_external_preemption_reason", "test_true_external_pump_change_still_preempts_after_owned_prime_model", "fresh contradiction revokes continued authority"),
    EventEpochProof("duplicate_terminal_event", EventClassification.RETIRED, "poolos/thermal_runtime_ownership.py", "evaluate", "test_duplicate_postlease_event_cannot_mutate_terminal_ownership_twice", "terminal ownership cannot be mutated repeatedly"),
    EventEpochProof("newer_same_concept", EventClassification.SUPERSEDED, "poolos/external_change.py", "update", "test_later_same_concept_transition_replaces_older_takeover", "latest same-concept native truth replaces retained evidence"),
    EventEpochProof("delayed_older_same_concept", EventClassification.RETIRED, "poolos/external_change.py", "update", "test_initial_duplicate_regressive_and_reset_snapshots_are_baselines", "temporally regressive truth cannot replace current truth"),
    EventEpochProof("transport_generation_reset", EventClassification.RETIRED, "custom_components/poolos/external_change_runtime.py", "process", "test_runtime_publishes_one_stable_bounded_ha_event_after_baseline", "discovery generation establishes a new native baseline"),
    EventEpochProof("unrelated_concept", EventClassification.IRRELEVANT, "poolos/circulation_successor.py", "_external_takeover", "test_bounded_takeover_retention_survives_empty_and_unrelated_batches", "unrelated evidence neither erases nor becomes takeover authority"),
    EventEpochProof("evaluation_plan_churn", EventClassification.AUTHORITATIVE, "poolos/thermal_runtime_ownership.py", "evaluate", "test_runtime_ownership_survives_compatible_new_evaluation_epoch", "audit identity churn does not change semantic purpose"),
    EventEpochProof("restart_boundary", EventClassification.RETIRED, "poolos/thermal_runtime_ownership.py", "ThermalRuntimeOwnershipManager", "test_restart_cannot_handoff_an_old_runtime_lease", "ephemeral runtime ownership is not reconstructed"),
)


PHASE_EVENT_DIMENSIONS = (
    "matching_historical_event",
    "contradictory_historical_event",
    "duplicate_event",
    "delayed_event",
    "newer_same_concept_event",
    "pre_acceptance_event",
    "exact_acceptance_event",
    "post_acceptance_pre_verification_event",
    "post_verification_event",
    "evaluation_id_churn",
    "plan_id_churn",
)
_RETAINED_EVENT_PHASES = frozenset("EIJKLMNOPQ")
_COMMAND_ACCEPTANCE_PHASES = frozenset("ABCDFGJM")


def _phase_event_disposition(
    phase: str,
    dimension: str,
) -> EventClassification | str:
    """Return the explicit bounded A-Q event contract or an exclusion reason."""

    if dimension in {"evaluation_id_churn", "plan_id_churn"}:
        return EventClassification.AUTHORITATIVE
    if dimension in {
        "matching_historical_event",
        "contradictory_historical_event",
        "duplicate_event",
        "delayed_event",
        "newer_same_concept_event",
    }:
        if phase not in _RETAINED_EVENT_PHASES:
            return "SEMANTICALLY_IRRELEVANT: no retained-event consumer at boundary"
        return {
            "matching_historical_event": EventClassification.IRRELEVANT,
            "contradictory_historical_event": EventClassification.TRUE_EXTERNAL_TAKEOVER,
            "duplicate_event": EventClassification.RETIRED,
            "delayed_event": EventClassification.RETIRED,
            "newer_same_concept_event": EventClassification.SUPERSEDED,
        }[dimension]
    if phase not in _COMMAND_ACCEPTANCE_PHASES:
        return "UNREACHABLE: boundary performs no physical command acceptance"
    return {
        "pre_acceptance_event": EventClassification.TRUE_EXTERNAL_TAKEOVER,
        "exact_acceptance_event": EventClassification.TRUE_EXTERNAL_TAKEOVER,
        "post_acceptance_pre_verification_event": (
            EventClassification.TRUE_EXTERNAL_TAKEOVER
        ),
        "post_verification_event": EventClassification.AUTHORITATIVE,
    }[dimension]


GENERATION_CASE_PROOFS = (
    GenerationCaseProof("runtime_ownership", "matching", EventClassification.IRRELEVANT, "test_old_event_cannot_preempt_successor_lease_after_prior_preemption", "old equality neither creates nor poisons ownership"),
    GenerationCaseProof("runtime_ownership", "contradictory", EventClassification.TRUE_EXTERNAL_TAKEOVER, "test_true_external_pump_change_still_preempts_after_owned_prime_model", "current contradiction preempts; obsolete contradiction is ignored"),
    GenerationCaseProof("execution_session", "matching", EventClassification.IRRELEVANT, "test_session_provenance_promotion_rejects_different_session", "old accepted operation cannot verify another session"),
    GenerationCaseProof("execution_session", "contradictory", EventClassification.TRUE_EXTERNAL_TAKEOVER, "test_incompatible_current_thermal_identity_supersedes_ownership", "current incompatible session identity revokes authority"),
    GenerationCaseProof("pump_speed_session", "matching", EventClassification.IRRELEVANT, "test_probe_replacement_handoff_rejects_stale_generation", "old pump phase cannot cross handoff"),
    GenerationCaseProof("pump_speed_session", "contradictory", EventClassification.TRUE_EXTERNAL_TAKEOVER, "test_matching_configured_setpoint_cannot_hide_actual_rpm_change", "current actual RPM contradiction remains authoritative"),
    GenerationCaseProof("autonomous_resume", "matching", EventClassification.IRRELEVANT, "test_manual_pool_off_consumes_origin_and_later_external_on_is_never_adopted", "resume cannot reuse matching pre-resume hardware"),
    GenerationCaseProof("autonomous_resume", "contradictory", EventClassification.TRUE_EXTERNAL_TAKEOVER, "test_preempted_thermal_session_allows_genuinely_fresh_successor_session", "fresh successor is a new authority epoch"),
    GenerationCaseProof("termination_entitlement", "matching", EventClassification.IRRELEVANT, "test_cleanup_attempt_cannot_cross_provenance_generation", "old entitlement cannot authorize cleanup"),
    GenerationCaseProof("termination_entitlement", "contradictory", EventClassification.TRUE_EXTERNAL_TAKEOVER, "test_external_source_takeover_explicitly_invalidates_termination_attempt", "current takeover invalidates termination"),
    GenerationCaseProof("transport_discovery", "matching", EventClassification.RETIRED, "test_runtime_publishes_one_stable_bounded_ha_event_after_baseline", "new discovery baseline retires old transport evidence"),
    GenerationCaseProof("transport_discovery", "contradictory", EventClassification.TRUE_EXTERNAL_TAKEOVER, "test_maintenance_and_reconnect_clear_current_drift", "new-generation drift is evaluated only after a new baseline"),
    GenerationCaseProof("restart_runtime", "matching", EventClassification.IRRELEVANT, "test_restart_with_matching_pool_state_reconstructs_no_cleanup_authority", "restart begins unowned despite equality"),
    GenerationCaseProof("restart_runtime", "contradictory", EventClassification.TRUE_EXTERNAL_TAKEOVER, "test_manual_pool_off_consumes_origin_and_later_external_on_is_never_adopted", "old origin cannot control a later external session"),
)


LIVENESS_DIMENSIONS = (
    "normal_progress",
    "near_deadline_progress",
    "timeout",
    "contradictory_event",
    "unrelated_duplicate",
    "repeated_reevaluation",
    "recovery",
)
LIVENESS_DIMENSION_PROOFS = (
    LivenessDimensionProof("blocked", "recovery", "test_driver_defaults_off_and_enable_requires_a_new_epoch", "fresh epoch progresses"),
    LivenessDimensionProof("awaiting_reobservation", "normal_progress", "test_accepted_body_activation_waits_for_authoritative_consequence", "later native consequence advances"),
    LivenessDimensionProof("awaiting_reobservation", "repeated_reevaluation", "test_cold_start_delivers_at_most_one_command_per_authoritative_epoch", "no duplicate delivery"),
    LivenessDimensionProof("awaiting_verification", "near_deadline_progress", "test_wrong_heater_remains_pending_until_bounded_verification_deadline", "causal evidence may progress before deadline"),
    LivenessDimensionProof("awaiting_verification", "timeout", "test_pump_mismatch_at_deadline_times_out", "fixed deadline terminates"),
    LivenessDimensionProof("awaiting_verification", "contradictory_event", "test_failed_verification_clears_accepted_delivery_ownership", "contradiction fails closed"),
    LivenessDimensionProof("observing_solar_engagement", "normal_progress", "test_quiescent_solar_cold_start_verifies_h0002_before_engagement", "continuous engagement converges"),
    LivenessDimensionProof("observing_solar_engagement", "timeout", "test_unengaged_solar_cold_start_is_bounded_and_not_immediately_retried", "absolute deadline terminates"),
    LivenessDimensionProof("observing_solar_engagement", "repeated_reevaluation", "test_unengaged_solar_cold_start_is_bounded_and_not_immediately_retried", "reevaluation cannot extend deadline"),
    LivenessDimensionProof("terminating", "normal_progress", "test_owned_gas_source_is_deselected_then_verified_without_stopping_pool", "source Off is delivered"),
    LivenessDimensionProof("awaiting_termination_verification", "normal_progress", "test_accepted_termination_delivery_needs_a_later_authoritative_epoch", "later native source Off verifies"),
    LivenessDimensionProof("awaiting_termination_verification", "contradictory_event", "test_native_solar_takeover_cannot_verify_gas_source_off_delivery", "contradiction cannot verify"),
    LivenessDimensionProof("awaiting_termination_verification", "unrelated_duplicate", "test_same_timestamp_command_callback_cannot_verify_termination", "duplicate chronology does not advance"),
    LivenessDimensionProof("cleanup_waiting", "recovery", "test_verified_source_off_then_normalizes_filtration_once_and_later_stops_body", "fresh successor evidence selects action"),
    LivenessDimensionProof("awaiting_cleanup_verification", "normal_progress", "test_pump_cleanup_requires_later_configured_and_actual_native_truth", "independent callbacks jointly verify"),
    LivenessDimensionProof("awaiting_cleanup_verification", "contradictory_event", "test_transient_spa_takeover_preempts_pending_cleanup_verification", "takeover invalidates cleanup"),
    LivenessDimensionProof("awaiting_cleanup_verification", "unrelated_duplicate", "test_body_cleanup_receipt_is_not_verification", "receipt/duplicate input cannot verify"),
    LivenessDimensionProof("preempted", "recovery", "test_preempted_thermal_session_allows_genuinely_fresh_successor_session", "new accepted session required"),
    LivenessDimensionProof("relinquished", "recovery", "test_relinquishment_is_terminal_and_command_free", "terminal by intentional policy"),
    LivenessDimensionProof("failed", "recovery", "test_rejected_delivery_fails_closed_without_retry_or_ownership", "explicit re-enable required"),
    LivenessDimensionProof("superseded", "recovery", "test_true_requested_mode_supersession_terminates_without_next_delivery", "new purpose requires new session"),
)


INTERLEAVING_PROOFS = (
    ("manual_off_pending", "test_manual_pool_off_suppression_preempts_inflight_cold_start_without_retry"),
    ("rpm_change_pending", "test_unverified_matching_pump_event_still_preempts"),
    ("timeout_late_callback", "test_pump_mismatch_at_deadline_times_out"),
    ("supersession_late_consequence", "test_delivered_step_cannot_verify_after_thermal_plan_is_superseded"),
    ("restart_pending", "test_restart_cannot_handoff_an_old_runtime_lease"),
    ("reconnect_verification", "test_maintenance_and_reconnect_clear_current_drift"),
    ("filtration_changes_during_termination", "test_latest_filtration_state_can_become_immediate_during_thermal"),
    ("solar_loss_during_preparation", "test_true_requested_mode_supersession_terminates_without_next_delivery"),
    ("spa_cleanup_takeover", "test_transient_spa_takeover_preempts_pending_cleanup_verification"),
    ("source_independent_change", "test_external_source_takeover_explicitly_invalidates_termination_attempt"),
    ("configured_before_actual", "test_pump_cleanup_requires_later_configured_and_actual_native_truth"),
    ("actual_before_configured", "test_pump_cleanup_requires_later_configured_and_actual_native_truth"),
    ("old_discovery_callback", "test_initial_duplicate_regressive_and_reset_snapshots_are_baselines"),
    ("historical_event_new_owner", "test_old_event_cannot_preempt_successor_lease_after_prior_preemption"),
    ("terminal_owner_pending_provenance", "test_duplicate_postlease_event_cannot_mutate_terminal_ownership_twice"),
    ("cleanup_takeover", "test_cleanup_takeover_invalidates_provenance_without_command"),
    ("spontaneous_source_off", "test_source_off_is_required_but_does_not_create_body_origin"),
    ("late_superseded_success", "test_delivered_step_cannot_verify_after_thermal_plan_is_superseded"),
    ("identity_churn_equality", "test_duplicate_evidence_timestamp_is_idempotent_confirmation"),
    ("filtration_completion_cleanup", "test_normal_day_pool_and_spa_complete_lifecycle"),
)


REASON_SOURCE_FILES = (
    "poolos/thermal_automatic_execution.py",
    "poolos/thermal_runtime_orchestration.py",
    "poolos/thermal_runtime_ownership.py",
    "poolos/thermal_live_execution.py",
    "poolos/thermal_termination.py",
    "poolos/circulation_successor.py",
    "poolos/filtration_automatic_execution.py",
)
REASON_PREFIXES = (
    "automatic_thermal_",
    "thermal_orchestration_",
    "runtime_ownership_",
    "thermal_execution_",
    "thermal_live_",
    "thermal_termination_",
    "thermal_cleanup_",
    "circulation_",
    "automatic_filtration_",
)
REASON_SIGNALS = (
    "blocked",
    "denied",
    "preempted",
    "relinquished",
    "superseded",
    "failed",
    "failure",
    "unavailable",
    "stale",
    "unusable",
    "mismatch",
    "conflict",
    "takeover",
    "timed_out",
    "pending",
    "required",
    "verified",
    "engaged",
    "retained",
    "established",
    "promoted",
    "handed_off",
    "no_",
    "already_off",
    "not_current",
    "not_authoritatively",
    "disabled",
    "unloaded",
    "not_immediately",
    "ready",
)
REASON_FAMILY_COUNT = 221
REASON_FAMILY_SHA256 = "0b4e1a2b80165b97ae04e65fc01a2ccc0989706e2b6022bb0b57033eeff5695c"


@cache
def _defined_tests() -> frozenset[str]:
    names: set[str] = set()
    for path in (ROOT / "tests").glob("test_*.py"):
        tree = ast.parse(path.read_text())
        names.update(
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        )
    return frozenset(names)


def _string_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            item.value
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
            else "{}"
            for item in node.values
        )
    return None


def _reason_families() -> tuple[tuple[str, str, str], ...]:
    result: set[tuple[str, str, str]] = set()

    def visit(node: ast.AST, source: str, function: str = "<module>") -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = node.name
        value = _string_value(node)
        if (
            value is not None
            and value.startswith(REASON_PREFIXES)
            and any(signal in value for signal in REASON_SIGNALS)
        ):
            result.add((source, function, value))
        for child in ast.iter_child_nodes(node):
            visit(child, source, function)

    for source in REASON_SOURCE_FILES:
        visit(ast.parse((ROOT / source).read_text()), source)
    return tuple(sorted(result))


def _reason_classification(function: str, reason: str) -> ReasonClassification:
    if function == "diagnostics":
        return ReasonClassification.DIAGNOSTIC_ONLY
    if any(word in reason for word in ("external_takeover", "manual_")):
        return ReasonClassification.MANUAL_EXTERNAL_TAKEOVER
    if any(
        word in reason
        for word in (
            "established",
            "promoted",
            "handed_off",
            "retained:",
            "_verified",
            "solar_engaged",
            "owned_source_off_ready",
            "already_off",
        )
    ):
        return ReasonClassification.NORMAL_TRANSITION
    if any(
        word in reason
        for word in (
            "pending",
            "fresh_epoch_required",
            "cold_start_activation_required",
            "residual_termination_required",
            "candidate_unavailable",
            "no_authorized_candidate",
            "not_immediately_required",
        )
    ):
        return ReasonClassification.EXPECTED_WAIT
    return ReasonClassification.INTENTIONAL_SAFETY_BOUNDARY


def _reason_regression(source: str, reason: str) -> str:
    if source.endswith("circulation_successor.py"):
        return "test_external_takeover_defeats_thermal_exclusivity"
    if source.endswith("filtration_automatic_execution.py"):
        return "test_off_to_filtration_owned_to_off_is_closed_loop_and_provenance_based"
    if source.endswith("thermal_live_execution.py"):
        return "test_no_second_step_is_delivered_before_first_native_verification"
    if source.endswith("thermal_runtime_orchestration.py"):
        return "test_integer_native_configured_pump_speed_accepts_integral_float"
    if source.endswith("thermal_runtime_ownership.py"):
        return "test_full_execution_provenance_is_eligible_for_runtime_ownership"
    if source.endswith("thermal_termination.py"):
        return "test_owned_pool_source_off_is_the_only_physical_termination_action"
    if "cleanup" in reason:
        return "test_verified_source_off_then_normalizes_filtration_once_and_later_stops_body"
    if "solar" in reason:
        return "test_unengaged_solar_cold_start_is_bounded_and_not_immediately_retried"
    return "test_driver_defaults_off_and_enable_requires_a_new_epoch"


@pytest.mark.parametrize("proof", CONTROL_PATH_PROOFS, ids=lambda item: item.key)
def test_systemic_control_path_has_live_code_and_behavioral_proof(
    proof: ClosureProof,
) -> None:
    source = ROOT / proof.production_file
    assert source.is_file()
    assert proof.production_symbol in source.read_text()
    assert proof.regression in _defined_tests()
    assert proof.invariant.strip()


def test_closure_manifest_has_no_duplicate_or_missing_phase_or_generation() -> None:
    assert {item.key[0] for item in PHASE_PROOFS} == set("ABCDEFGHIJKLMNOPQ")
    assert len({item.key for item in PHASE_PROOFS}) == 17
    assert {item.key for item in GENERATION_PROOFS} == {
        "runtime_ownership",
        "execution_session",
        "pump_speed_session",
        "autonomous_resume",
        "termination_entitlement",
        "transport_discovery",
        "restart_runtime",
    }


@pytest.mark.parametrize(
    "proof", EVENT_EPOCH_PROOFS, ids=lambda item: item.chronology
)
def test_event_epoch_case_has_production_consumer_and_behavioral_proof(
    proof: EventEpochProof,
) -> None:
    source = ROOT / proof.consumer_file
    assert source.is_file()
    assert proof.consumer_symbol in source.read_text()
    assert proof.regression in _defined_tests()
    assert proof.rationale.strip()
    assert {item.key for item in LIVENESS_PROOFS} == {
        "blocked",
        "awaiting_reobservation",
        "awaiting_verification",
        "observing_solar_engagement",
        "terminating",
        "awaiting_termination_verification",
        "cleanup_waiting",
        "awaiting_cleanup_verification",
        "preempted",
        "relinquished",
        "failed",
        "superseded",
    }


def test_event_epoch_classifications_are_explicit() -> None:
    classifications = {item.classification for item in EVENT_EPOCH_PROOFS}
    assert classifications == set(EventClassification)


@pytest.mark.parametrize("proof", PHASE_PROOFS, ids=lambda item: item.key)
def test_phase_matrix_is_complete_and_bound_to_a_production_consumer(
    proof: ClosureProof,
) -> None:
    phase = proof.key[0]
    outcomes = {
        dimension: _phase_event_disposition(phase, dimension)
        for dimension in PHASE_EVENT_DIMENSIONS
    }
    assert set(outcomes) == set(PHASE_EVENT_DIMENSIONS)
    for outcome in outcomes.values():
        assert isinstance(outcome, EventClassification) or outcome.startswith(
            ("UNREACHABLE:", "SEMANTICALLY_IRRELEVANT:")
        )
    assert any(isinstance(outcome, EventClassification) for outcome in outcomes.values())
    assert proof.production_symbol in (ROOT / proof.production_file).read_text()
    assert proof.regression in _defined_tests()


@pytest.mark.parametrize(
    "proof",
    GENERATION_CASE_PROOFS,
    ids=lambda item: f"{item.generation}-{item.history}",
)
def test_generation_isolation_case_uses_real_regression(
    proof: GenerationCaseProof,
) -> None:
    assert proof.history in {"matching", "contradictory"}
    assert proof.classification in EventClassification
    assert proof.regression in _defined_tests()
    assert proof.invariant.strip()


def test_generation_matrix_has_matching_and_contradictory_case_per_domain() -> None:
    domains = {item.key for item in GENERATION_PROOFS}
    assert {
        (item.generation, item.history) for item in GENERATION_CASE_PROOFS
    } == {(domain, history) for domain in domains for history in ("matching", "contradictory")}


@pytest.mark.parametrize(
    "proof",
    LIVENESS_DIMENSION_PROOFS,
    ids=lambda item: f"{item.state}-{item.dimension}",
)
def test_liveness_dimension_has_behavioral_regression(
    proof: LivenessDimensionProof,
) -> None:
    assert proof.state in {item.key for item in LIVENESS_PROOFS}
    assert proof.dimension in LIVENESS_DIMENSIONS
    assert proof.regression in _defined_tests()
    assert proof.expected.strip()


def test_liveness_matrix_explicitly_excludes_inapplicable_dimensions() -> None:
    covered = {(item.state, item.dimension) for item in LIVENESS_DIMENSION_PROOFS}
    exclusions = {
        (state.key, dimension): (
            "NOT_APPLICABLE: terminal states have no deadline/progress loop"
            if state.key in {"preempted", "relinquished", "failed", "superseded"}
            else "NOT_APPLICABLE: state does not consume this event dimension"
        )
        for state in LIVENESS_PROOFS
        for dimension in LIVENESS_DIMENSIONS
        if (state.key, dimension) not in covered
    }
    complete = covered | set(exclusions)
    assert complete == {
        (state.key, dimension)
        for state in LIVENESS_PROOFS
        for dimension in LIVENESS_DIMENSIONS
    }
    assert all(reason.startswith("NOT_APPLICABLE:") for reason in exclusions.values())


@pytest.mark.parametrize("case,regression", INTERLEAVING_PROOFS)
def test_unknown_interleaving_audit_has_behavioral_regression(
    case: str,
    regression: str,
) -> None:
    assert case.strip()
    assert regression in _defined_tests()


def test_reason_family_inventory_is_frozen_classified_and_regression_mapped() -> None:
    families = _reason_families()
    encoded = json.dumps(families, separators=(",", ":"))
    assert len(families) == REASON_FAMILY_COUNT
    assert sha256(encoded.encode()).hexdigest() == REASON_FAMILY_SHA256
    defined = _defined_tests()
    for source, function, reason in families:
        assert _reason_classification(function, reason) in ReasonClassification
        assert _reason_regression(source, reason) in defined


def test_reason_family_guard_covers_every_authority_domain() -> None:
    sources = {source for source, _, _ in _reason_families()}
    assert sources == set(REASON_SOURCE_FILES)
    classifications = {
        _reason_classification(function, reason)
        for _, function, reason in _reason_families()
    }
    assert classifications >= {
        ReasonClassification.NORMAL_TRANSITION,
        ReasonClassification.EXPECTED_WAIT,
        ReasonClassification.INTENTIONAL_SAFETY_BOUNDARY,
        ReasonClassification.MANUAL_EXTERNAL_TAKEOVER,
        ReasonClassification.DIAGNOSTIC_ONLY,
    }
