# Ownership contract implementation traceability

## Baseline and artifact contract

Stage 1 reviewed main `9307e6d882cfa847e4be97f4e1e755174e34b5ac`, the v0.11.23
release merge. This stage changes documentation/specifications and a JSON mapping
only. It does not implement the scenarios, revise test expectations, enable a
new authority path, or establish physical commissioning.

The [accepted contract](PoolOS_Ownership_Scenario_Contract.txt) is the complete,
unmodified source supplied by the owner. SHA-256:
`0759872ed4ecdfb24eb762a7e59d1b2c27c0c6ae3c84c92cd9c02cf04099b1bd`.
Its pre-incorporation precedence is superseded by explicit incorporation in
AGENTS.md and [ADR-110](../adr/ADR-110-ownership-contract-semantics.md). Do not edit
the imported source to resolve an implementation problem. An owner-approved
contract revision needs explicit history, a new hash and complete mapping review.

[scenario_traceability.json](scenario_traceability.json) contains exactly IDs 1–90,
the original titles (whitespace normalized only), verbatim Expected sections,
required mechanisms, current production/test areas, audited behavior/gap, one of
the requested classification values, and stable future regression IDs OWN-001
through OWN-090. Specific test nodes are included where identified. A file-level
reference is an inspection pointer, not proof of the whole scenario. Reset has
no current behavioral regression even where related policy/safety files exist.

SATISFIED means the audited baseline mechanism for that scenario is supported by
named behavioral evidence; it does not certify the entire new architecture or
physical execution. Every entry still requires an explicit contract regression
and endpoint/authority assertions before the feature can claim full compliance.
PARTIALLY SATISFIED must not be promoted merely because a neighboring test passes.
Future implementations should add exact test nodes/results per OWN ID, retaining
baseline assessment history and updating the reviewed implementation commit.

## Current conflicts requiring test splits later

No listed test is removed or altered in Stage 1. Maintain negative safety and
chronology assertions while changing the attributed cause in the implementation
stage. For each operator case use a typed positive request fixture. Repeat the
same physical change without that fixture; this must be ambiguity/convergence,
not invented External ownership. Fixtures are not proof native ICP/OCP telemetry
currently exposes operator identity.

| Current tests/areas | Required future treatment |
| --- | --- |
| `tests/test_systemic_autonomy_closure_guard.py`: `EVENT_EPOCH_PROOFS`, phase/generation classification and reason-family guard | Split contradiction/pre-acceptance/unverified from TRUE_EXTERNAL_TAKEOVER. Old evidence still cannot verify/adopt; genuine positive intent still preempts only its domain. Retain complete A–Q, generation, liveness and reason coverage; review changed inventory rather than blindly refreshing hashes. |
| `tests/test_thermal_runtime_ownership.py::test_true_external_pump_change_still_preempts_after_owned_prime_model` | Same RPM change with positive intent yields Pump External only; no intent yields bounded drift recovery. |
| `tests/test_thermal_runtime_ownership.py::test_unverified_matching_pump_event_still_preempts` | Unverified/equal/pre-acceptance evidence cannot prove consequence or create origin. It also cannot alone prove manual takeover. Add positive-operator control separately. |
| `test_owned_pump_and_source_fail_closed_on_relevant_evidence`, `test_matching_configured_setpoint_cannot_hide_actual_rpm_change`, `test_matching_actual_rpm_cannot_hide_external_configured_setpoint_change` in runtime ownership tests | Preserve contradictory/stale evidence command denial; distinguish origin retention, domain permission and operator attribution. |
| `tests/test_thermal_automatic_execution.py::test_preempted_thermal_session_allows_genuinely_fresh_successor_session` | Prove actual independent opportunity, not just a fresh evaluation/session ID. Include HA manual suppression and cancellation identity. |
| `test_runtime_ownership_is_superseded_by_changed_execution_purpose`, `test_incompatible_current_thermal_identity_supersedes_ownership` in runtime ownership tests | Obsolete execution still stops; compatible continuous BODY origin transfers explicitly. Cross-body/incompatible/stale negative cases remain denied. |
| `tests/test_pump_speed_session.py::test_new_external_transition_is_adopted_only_after_session_establishment`, `test_external_return_to_baseline_cancels_override_without_mutating_policy` | Unmatched configured transition cannot infer manual intent. Hand-back requires positive request and verification against current desired value, not equality with an arbitrary baseline. |
| `tests/test_pump_speed_session.py::test_explicit_baseline_request_hands_back_governance_even_if_delivery_fails` | Separate immediate deliberate relinquishment of override intent from verified command permission/convergence. Failed delivery cannot claim physical hand-back completed. |
| `tests/test_thermal_termination.py::test_external_pump_takeover_invalidates_source_cleanup_too`, circulation successor takeover/retention tests | Preserve safe source/body requirements while allowing domain-scoped override and explicit body completion. Historical event retention is not permanent operator intent. |
| `tests/test_filtration_automatic_execution.py::test_material_actual_rpm_change_after_pump_provenance_preempts`, `test_rejected_delivery_establishes_no_ownership_and_requires_reenable` | Separate unexplained drift, positive intervention and delivery fault. Retain exact accepted/verified proofs and no replay; add legitimate autonomous recovery. |
| `tests/test_thermal_automatic_execution.py::test_quiescent_solar_cold_start_verifies_h0002_before_engagement`, `test_unengaged_solar_cold_start_is_bounded_and_not_immediately_retried` | Keep source verification and fixed engagement bounds; distinguish preparation requirement from active Solar RPM. Non-engagement is not delivery failure. |
| `tests/test_thermal_automatic_execution.py::test_owned_solar_session_survives_native_solar_active_drop` | Keep existing assertion; extend through native RPM change and later policy alignment/termination. Constant-RPM Active-drop coverage is insufficient. |
| `tests/test_thermal_automatic_execution.py::test_manual_pool_off_consumes_origin_and_later_external_on_is_never_adopted` | Old origin stays invalid. Add genuinely independent later prospective adoption without resurrecting its receipts. |
| `tests/test_filtration_restart_prospective_adoption.py` | Keep one-shot restart safety; extend to thermal/current policy and adopted-to-thermal transfer without no-op receipt fabrication. |
| `tests/test_pool_automatic_control_suppression.py` | Preserve same-opportunity cancellation and durable restraint; add independent TOU/future-opportunity acquisition before day rollover. |
| `tests/test_home_assistant_external_change_runtime.py`, `tests/test_external_change.py`, `tests/test_home_assistant_pump_speed_session.py` | Trace positive intent versus native values from adapter through shared classifier and consumers; include same-frame manual/transition races. |
| `tests/test_grid_outage_physical_safety.py`, `tests/test_home_assistant_grid_outage_runtime.py` | Keep canonical safety and exact allowlists; do not call missing attribution manual takeover or let it defeat an active mandatory safety rule. |

Also extend final body-Off verification tests with fresh body Off but nonzero RPM:
this cannot certify full session shutdown. Preserve command-free waiting, exact
cleanup generation, and no generic StopPump authority. Keep all residual capture
disposition tests in `tests/test_residual_cleanup_transfer.py`, particularly failed
capture retention and new-generation invalidation.

## Future production areas

The JSON lists per-scenario paths. Coherent implementation is expected in these
existing boundaries, not a second ownership system:

- `poolos/thermal_runtime_ownership.py`, `thermal_execution_currentness.py`,
  `thermal_runtime_orchestration.py`: body lifecycle, scoped authority, typed
  handoff/currentness and historical receipt distinction.
- `poolos/external_change.py`, `physical_command_authority.py`,
  `custom_components/poolos/external_change_runtime.py`, `manual_intellicenter.py`:
  shared evidence classification, request origin and final generation/intent fence.
- `poolos/pump_speed_session.py`, `thermal_operating_purpose.py`,
  `custom_components/poolos/pump_speed_session.py`: actual purpose, override scope,
  hand-back and bounded convergence.
- `poolos/thermal_live_execution.py`, `thermal_automatic_execution.py`,
  `thermal_runtime_assessment.py`, `thermal_termination.py`,
  `thermal_circulation_cleanup.py`: preparation/source/active semantics, fixed
  episodes, domain-safe completion and pump-zero verification.
- `poolos/pool_circulation_ownership.py`, `circulation_successor.py`,
  `filtration_automatic_execution.py`: exclusive transfers, prospective origins,
  immediate obligation versus deferred debt and completion.
- `poolos/pool_automatic_control_suppression.py`, `spa_thermal_policy.py`,
  `custom_components/poolos/manual_thermal.py`, `select.py`, `climate.py`,
  `switch.py`, `__init__.py`: semantic opportunity cancellation, user Spa lifetime,
  current/durable intent, restart and explicit recovery boundaries.
- Existing canonical grid safety and HA adapter modules: classification and intent
  integration only within reviewed safety scope.
- `custom_components/poolos/button.py`, `sensor.py`, `binary_sensor.py`,
  `const.py` and diagnostics publication (new localization resources if needed): explicit
  Reset and bounded per-domain observability. Separate persistence schema only
  where necessary for positively evidenced durable intent; reuse owned policy
  and accounting stores.

## Proposed implementation commits after separate authorization

1. **Canonical authority/evidence model.** Extend existing provenance models with
   prospective origin, domain authority, health, permission and positive-intent
   evidence. Introduce stable body/opportunity and recovery identities. Add
   observation-only diagnostics and unit-level no-authority negative tests.
2. **Attribution and bounded convergence.** Use one classifier across runtime,
   pump session, termination and filtration. Add finite episode budgets and
   idempotent correction through the existing gateway. Split same-stimulus tests
   with/without intent; preserve causality and every safety deny.
3. **Continuous body lifecycle and selected/active execution.** Preserve BODY
   across compatible purposes using typed transfers. Keep immutable obsolete
   execution stopped. Separate preparation from active Solar RPM, preserve armed
   H0002 neutralization, and verify source/body/pump-zero completion.
4. **Manual domain scope and opportunity boundaries.** PUMP/THERMAL independent
   overrides and verified hand-back; BODY cancellation of current opportunity;
   independent TOU/new-purpose reacquisition; native durable-policy gestures only
   with defensible evidence. Add same-window operator races.
5. **Prospective adoption and restart.** Generalize the existing adoption boundary
   to independent eligible purposes/user Spa requests, preserve correct completion
   scope, fence old generations, and add bounded durable-intent migration and
   long-downtime recovery. Do not persist live execution grants.
6. **Explicit Reset and HA ownership.** Add reviewed reduction authority and new
   generation fencing, preserve policy/accounting, verify safe baseline then
   reevaluate. Publish all scenario-90 fields from one canonical bounded snapshot.
7. **Complete contract integration and migration proof.** Bind OWN-001–090 to
   deterministic regressions, update the historical systemic guard with reviewed
   classifications, and test complete daily cycles through native HA composition,
   failures, restarts and successor ordering. Finish documentation, release notes
   and commissioning procedures. Validate full pytest, Ruff, MyPy, compileall,
   exact diff, CI, Hassfest and HACS; physical commissioning follows separately.

These are reviewable commits in one feature effort, not permission to ship partial
authority expansion. At each stage behavior-changing tests must fail for the
intended reason before production edits. Stop after this Stage 1 documentation
commit until implementation is explicitly authorized.

## Engineering parameters and migration constraints

The outcomes are frozen; these implementation details need explicit reviewed
choices and tests before enabling their respective capabilities:

- Positive ICP/OCP request provenance: current native values lack actor proof.
  Determine what trustworthy request evidence is actually available; unsupported
  origin remains ambiguous with recovery, never a heuristic External label.
- Finite retry counts, convergence envelopes/deadlines and long-downtime intent
  lifetime: reuse applicable existing safety budgets, specify non-renewal and
  recovery events, and do not expand freshness/tolerance to hide failure.
- Preparation flow and active Solar RPM ordering: distinguish independently
  justified protection from operating speed; preserve native cold-start source
  neutralization. Validate with fake native sequences before physical review.
- Body completion with a manual source override and Reset reduction: explicitly
  authorize safe session-ending source/body steps; no normal source fighting or
  generic StopPump inferred from a retained body receipt.
- Durable records: versioned, bounded, malformed-data fail-closed; preserve known
  operator scope without converting legacy unattributed events into actor proof.
  Policy/target/filtration ledgers remain single-source; existing counters survive.
- Entity compatibility: retain existing unique IDs where semantics still match;
  distinguish historical `owns_*` receipt booleans from current authority. Do not
  silently reinterpret old terminal reasons, recorder history or reenable flags.
- New body/domain/generation grants require reviewed authority and commissioning;
  no new Hot Tub, hydraulic routing, safety or native configuration scope is
  implied by this design. Tests cannot substitute for physical commissioning.

## Reproducible Stage 1 integrity check

Run from the repository root. This checks exact scenario coverage/text, contract
hash, referenced paths/test nodes and the docs-only diff. It does not execute or
claim any of the future scenario behaviors. No dedicated documentation checker
is configured in the repository's current CI; Python quality checks and pytest
remain the existing pipeline.

```bash
python3 - <<'PY'
from pathlib import Path
import ast
import hashlib
import json
import re
import subprocess

root = Path.cwd()
matrix = json.loads((root / 'docs/ownership/scenario_traceability.json').read_text())
source = root / matrix['normative_contract']
assert hashlib.sha256(source.read_bytes()).hexdigest() == matrix['contract_sha256']
body = source.read_text().split('SCENARIO MATRIX - ACCEPTED BEHAVIOR', 1)[1]
body = body.split('DERIVED ARCHITECTURAL REQUIREMENTS', 1)[0]
original = {}
for match in re.finditer(r'^([0-9]+)\. (.*?)(?=^[0-9]+\. |\Z)', body, re.M | re.S):
    title, expected = match[2].split('Expected:', 1)
    original[int(match[1])] = (
        ' '.join(title.split()), expected.split('\n======', 1)[0].strip()
    )
assert [row['scenario_id'] for row in matrix['scenarios']] == list(range(1, 91))
assert len(original) == 90
for row in matrix['scenarios']:
    sid = row['scenario_id']
    assert (row['title'], row['expected_contract_behavior']) == original[sid]
    assert row['implementation_status'] in matrix['status_vocabulary']
    assert row['required_semantic_mechanisms'] and row['current_behavior_and_gap']
    assert row['required_future_regressions'][0]['id'] == f'OWN-{sid:03d}'
    assert row['required_future_regressions'][0]['behavior']
    for path in row['relevant_production_areas'] + row['current_test_areas']:
        assert (root / path).is_file(), path
    for node in row['specific_baseline_test_nodes']:
        path, name = node.split('::')
        tree = ast.parse((root / path).read_text())
        assert any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == name for n in ast.walk(tree)), node
    if row['implementation_status'] == 'SATISFIED':
        assert row['specific_baseline_test_nodes']
changed = subprocess.check_output(
    ['git', 'diff', '--name-only', matrix['reviewed_main']], text=True
).splitlines()
assert all(path == 'AGENTS.md' or path.startswith('docs/') for path in changed)
print('90 exact scenarios; contract hash, mappings, test nodes and docs-only diff verified')
PY
git diff --check
```

Before staging, separately review `git status --short` and the exact untracked
documentation inventory; the tracked diff check alone cannot validate untracked
files. Stage only reviewed explicit paths. Never inspect or stage `.local_backups/`.
