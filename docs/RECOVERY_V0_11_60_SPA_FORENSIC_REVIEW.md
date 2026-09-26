# Recovery v0.11.60 cleanup and opportunistic Spa investigation

Date: 2026-09-23. Baseline: `676757a5a806b5dcdc76b8b826cc32f4c1ec0e38`
(`recovery/v0.11.48-opportunistic-spa`, v0.11.60).
Candidate branch: `fix/recovery-cleanup-native-evidence`.
No release, deployment, equipment access, or physical commissioning was performed.

## 1. Demonstrated root cause

The reproduction establishes Pool BODY through an accepted activation, observes
native configured circulation at 2600, accepts/verifies probe RPM 1500, and feeds
stable 81 F samples for the acquisition interval. Target is 78 F. Completion at
model second 123 supersedes the probe and retains the exact residual entitlement.
BODY/source observations are older than this boundary, but still inside the
120-second orchestration freshness contract.

`ThermalAutomaticExecutionDriver._capture_cleanup_provenance` correctly refuses
the transfer: selected-Off evidence predates the residual. The residual remains;
`cleanup_provenance` is **None**. Circulation arbitration checks BODY chronology
before its source-safe gate, so the visible blocker is
`circulation_body_activity_evidence_not_current`.

`PoolOSThermalAutomaticRuntime._sync_cleanup_topology_reobservation` in v0.11.60
watches only `driver.cleanup_provenance`. It returns before scheduling any read.
The observation needed to permit capture is requested only *after* capture. In
this reproduced failure the request is not lost, deduplicated, or assigned to a
wrong generation: **it is never requested**. The control that explicitly invokes
the production coordinator refresh crosses this boundary. Thus the reported live
symptoms have a deterministic repository-level causal reproduction; this is not
a claim to have retrieved new live observer logs.

A second defect exists in the reused read path. Its BODY query asks for STATUS,
SUBTYP and SNAME, not HEATER/HTMODE. The pinned `pyintellicenter==0.1.20`
`PoolModel.process_updates` returns only changed attributes, and
`ICModelController._apply_updates` invokes its callback only when that result is
nonempty. Unchanged STATUS therefore cannot trigger PoolOS's separate BODY
metadata worker. Republishing the whole cached source with a new snapshot time
is not a genuine source reobservation.

## 2. Red regression evidence

`tests/test_cleanup_native_reobservation_lifecycle.py` contains:

- `test_probe_residual_wait_requests_post_entitlement_native_evidence`:
  24 combinations of automatic/explicit-refresh control, pre-boundary evidence
  ages 1/9/119 seconds, and target/Solar-loss/Pool-priority/pump-timeout shutdown.
- `test_residual_reobservation_is_bounded_and_cannot_create_authority`: four
  cases covering unsuccessful reads, exceptions, invalidation and replacement.
- `test_cleanup_native_read_publishes_only_complete_current_replies`: seven
  cases covering unchanged values, changed source, missing source, empty reply,
  timeout, old generation and an intervening native update.

The final lifecycle regression was also run against an isolated tracked-file
export of the exact release commit. It fails with:

```text
AssertionError: Residual waiting must request native evidence before cleanup capture
assert []
```

With scheduling corrected but the old native request shape retained, it fails:

```text
Cleanup must actually read source selection, not refresh its cached timestamp
{'HEATER', 'HTMODE', 'STATUS'} <= {'SNAME', 'STATUS', 'SUBTYP'}
```

With the native/runtime fixes but the release's automatic driver retained in the
isolated export, the lifecycle reaches Spa activation but not heating:
`stable_epochs == 0`, with repeated source-Off / Spa-On / Spa-Off sequences.

After those fixes, requiring Spa OFF with actual pump900 to remain pending failed
with `Spa BODY OFF is not completed shutdown while pump remains nonzero` and
`driver.cleanup_provenance is None`. Adding pump-zero verification alone exposed
the adjacent `thermal_termination_hot_tub_topology_lost` disposal: the termination
policy expects the previously owned Spa to remain active. Both failures occurred
before the corresponding completion/verification correction.

The regression uses the production HA runtime scheduling function, coordinator
refresh method, independent transport read function, immutable native snapshot
and read adapter, then carries their returned values/timestamps into the actual
core evaluator/orchestrator/driver. Socket responses and HA services are test
doubles. The existing core frame/delivery harness supplies the remaining policy,
safety and acceptance fixtures. This is not a real HA event-loop or firmware test;
it does not claim byte-level protocol or hardware latency fidelity.

## 3. Corrections

### Cleanup scheduling

Watch the exact residual entitlement as well as captured cleanup provenance.
Request at most once for each boundary. Capture establishes its own later boundary
and receives its own read. Obsolete scheduled work checks the current token before
starting; unload cancels work. No deadline, authority, receipt or observation is
created by scheduling.

### Explicit cleanup evidence

The coordinator selects a cleanup-specific option on the existing read path.
Ordinary pump-session refresh is unchanged. Cleanup reads BODY/source fields,
pump evidence, sensors, PMPCIRC, shared circuits and controller mode. Replies must
cover the discovered identities and required known fields, including BODY
STATUS/HEATER/HTMODE and PUMP STATUS/RPM. Missing or changed identities fail closed.

Collect replies before applying them. Suppress only the synchronous callback from
applying this complete batch, then publish once explicitly. An unchanged response
is still a real read. Empty replies, timeout, reconnect/generation change or any
intervening published native snapshot cause abandonment, not cached-state refresh.
An adversarial test caught a batch overwriting newer live evidence during initial
implementation; the snapshot-identity fence now prevents that race.

Timestamp the successful batch with its conservative **read-start lower bound**.
A boundary created during the multi-query read cannot use an earlier reply as
post-boundary evidence just because the batch finished later. The tests advance
the clock between replies. No skew allowance or freshness relaxation is added.

### Acquisition completion between commands

Native Spa BODY activation can start circulation before an unissued prime. The
existing typed handoff can produce a READY acquisition execution. The next
observation makes Spa temperature trustworthy and changes its purpose to Solar.
The old driver routed this READY execution directly into purpose supersession;
its handoff branch covered awaiting-verification and no-active-session cases.

A READY execution with a still-OWNED BODY origin and a compatible typed successor
now enters that existing handoff path. Its obsolete next operation is not sent.
The ownership manager still checks exact predecessor/generation, body, mode,
topology, usable evidence and successor compatibility. New pump/source provenance
still requires accepted operations. No cross-body handoff is introduced.

### Spa shutdown verification

An accepted Spa-Off cleanup now requires fresh usable actual pump0 observed
strictly after delivery, in addition to the existing body verification. An
authoritative post-command Spa OFF with Pool OFF is the expected consequence,
not a reason to discard the pending attempt as lost active-Spa topology. While
the pump coasts down, retain only that attempt and its original absolute deadline;
no additional command is permitted by this waiting state. Other invalidating
topology results retain their existing behavior. If the pump stays at900, the
attempt faults at its unchanged deadline without duplicate delivery or fabricated
successful completion. This adds no generic StopPump operation.

## 4. Modeled endpoint and Spa continuation

The same driver/evaluator now completes:

Pool probe -> trusted 81 F / target 78 F -> residual read -> cleanup transfer ->
second read -> accepted Pool OFF -> Pool OFF / pump900 **still pending** ->
pump0 verified -> clean completion -> fresh Spa source-Off precondition ->
accepted Spa ON -> native2600 circulation -> trusted Spa evidence -> typed Solar
successor -> accepted 2900 and Solar selection -> observed Solar ACTIVE ->
more than 120 stable one-second epochs with unchanged Spa generation -> source
OFF -> Spa OFF / pump900 still pending -> actual pump0 -> clean Spa termination.

All three terminations run: target cap, sustained low roof, and Pool priority.
The priority case continues to a new Pool BODY origin/generation and Pool Solar
2900. Neither the original Pool origin nor the Spa origin authorizes that Pool
activation. No Gas command occurs. Spa's current repository trust policy accepts
fresh exclusive Spa circulation as temperature evidence; this test does not
invent an additional physical mixing/settling guarantee. The model raises roof
from the initial 125 F to 140 F for the default 130 F Spa qualification threshold.

## 5. Protected regression envelope

All listed existing suites remain part of the full pytest run. “Composed” below
means constituent regressions, not a claim of a new monolithic hardware simulation.

| # | Protected behavior | Evidence |
|---|---|---|
| 1 | Normal Pool Solar startup | thermal automatic/live/currentness suites |
| 2 | Owned Pool target shutdown | thermal automatic shutdown and new probe lifecycle |
| 3 | Adopted Pool target shutdown | `test_prospectively_adopted_pool_solar_owns_target_satisfied_shutdown` |
| 4 | Natural evening loss | thermal automatic Solar-loss regressions |
| 5 | Immediate filtration successor | circulation successor and filtration handoff tests |
| 6 | TOU-deferred loss | preempted-successor/deferred-filtration and policy tests |
| 7 | Overnight filtration completion | filtration accounting, TOU and automatic driver suites |
| 8 | 1500/2600/2900/3000 | pump baseline/session/priming and lifecycle suites |
| 9 | Manual Pool restraint | prospective adoption restraint and suppression tests |
| 10 | Manual Spa session | Spa user-session and operator-claim tests |
| 11 | Reset | `test_reset_poolos_control_is_first_class_reduction_recovery` (source-contract check; no new end-to-end Reset simulation) |
| 12 | Restart/reload | existing HA lifecycle and restart ownership tests |
| 13 | Unknown/stale | existing freshness matrix plus new incomplete-read tests |
| 14 | Domain independence | ownership lifecycle reconciliation and systemic guard |
| 15 | Opportunistic start | new continuous probe-to-Spa lifecycle |
| 16 | Spa Solar loss | new sustained-loss lifecycle case |
| 17 | Spa target cap | new target lifecycle case |
| 18 | No autonomous Gas | new command assertions and Spa policy tests |
| 19 | Pool priority | new Spa termination and distinct Pool Solar recovery |
| 20 | External Pool adoption -> shutdown -> Spa | composed adoption shutdown and fresh idle Spa admission coverage |
| 21 | Pool probe -> cleanup -> Spa | new continuous lifecycle |
| 22 | Native configured circulation | new Pool/Spa2600 activation consequences; existing unissued-prime tests |
| 23 | Unchanged native refresh | new no-change-callback native read regression |
| 24 | Failed refresh | new missing/empty/timeout/invalidation tests |
| 25 | Operator during cleanup | existing takeover/generation tests plus new intervening native update fence |
| 26 | Operator during Spa | Spa user-claim/restraint, currentness and domain-intent tests |
| 27 | Restart during/after Spa | `test_restart_does_not_reconstruct_opportunistic_spa_ownership_from_state` and Spa restart policy tests |

No filtration accounting, adoption policy, reset, restart persistence, gas policy,
operating baseline, circulation arbitration or final command gateway is changed.

## 6. Validation and limits

Final local validation:

- New cross-boundary regressions: 35 passed (included below).
- New regressions plus thermal automatic execution: 147 passed.
- Full pytest: **3505 passed**, one existing duplicate-ZIP-name warning.
- Ruff: passed across `poolos`, `intellicenter`, `tests`, and
  `custom_components/poolos` (no inspection of local backups).
- MyPy: passed, 217 source files.
- Compileall: passed across core, integration, IntelliCenter and tests.
- `git diff --check`: passed.

Upstream Hassfest was executed locally against the candidate: **1 integration,
0 invalid integrations**, all enabled validators passed. Upstream HACS manifest
and integration-manifest schemas passed against the local files. The full HACS
Action additionally reads a published GitHub repository/ref and is not equivalent
to these local schema checks. No hosted candidate CI result is claimed while the
branch remains unpublished.

Per the user's final publication direction, hand this candidate to the other chat
for review, explicit staging, commit, draft PR and hosted gates. No files were
staged or committed here. The PR base must be
`recovery/v0.11.48-opportunistic-spa`, not main. Full hosted Quality/Hassfest/HACS
remain required before claiming the complete CI gate is green. No merge, version
bump, tag, release, deployment or equipment action was performed.

The exact intended inventory is four production files:
`custom_components/poolos/coordinator.py`,
`custom_components/poolos/independent_intellicenter.py`,
`custom_components/poolos/thermal_automatic_runtime.py`, and
`poolos/thermal_automatic_execution.py`; one new test file:
`tests/test_cleanup_native_reobservation_lifecycle.py`; and two documents:
this report and `docs/DEVELOPMENT_HANDOFF.md`. Stage only these seven files after
review. `.local_backups/` was not inspected, modified or staged.

Physical uncertainties remain: complete GetParamList reply shape on this firmware,
read latency/callback ordering, native body default RPM, actual temperature mixing,
Solar engagement, and shared-pump coastdown. Missing evidence fails closed; it does
not establish an owner. Existing transport-wide snapshot semantics outside this
cleanup-specific complete read have not been redesigned.

## 7. Next physical confirmation (outside this task)

After review, release approval, and all required CI:

A. Start from verified idle and current policy. Enable the approved test once;
   verify Pool-only probe admission, accepted BODY, 1500 and trusted samples.
B. With Pool demand satisfied, inspect residual identity, real post-boundary read,
   source safe, Pool OFF and actual pump0. Do not proceed on body acknowledgment alone.
C. With roof qualified and no restraint, verify a NEW independent Spa generation.
D. Verify source precondition, Spa BODY acceptance, native configured circulation,
   and trustworthy Spa water evidence without inferred pump ownership.
E. Verify Solar physically ACTIVE, actual2900, all applicable Spa domains bound to
   that generation, and Gas OFF.
F. Hold at least two minutes. Inspect stable generation, no duplicate operations,
   no spurious External attribution or re-enable latch.
G. Raise the Pool target as an explicitly supervised commissioning stimulus:
   Spa yields through source/body/pump cleanup; a distinct Pool generation starts
   and Pool Solar resumes. Separately confirm Spa cap and Solar-loss alternatives.

At any failed checkpoint: STOP commissioning, preserve observations, request/reply
and command evidence with timestamps/generations, and restore normal Pool Solar
operation through the approved operator procedure. Do not immediately make another
live patch. This document authorizes no equipment action.

The next test is better supported by a red-before-green cross-boundary regression,
complete modeled Spa continuation, and explicit read-failure/race tests. It still
requires physical confirmation and hosted validation; local software evidence is
not a claim of commissioned Spa autonomy.
