# Native arbitration evidence: v1.0.22 forensic audit and candidate

Historical record: the later v1.0.24 recovery audit in
[SYSTEMIC_ARBITRATION_CURRENTNESS_AUDIT.md](SYSTEMIC_ARBITRATION_CURRENTNESS_AUDIT.md)
supersedes blanket rejection of intervening publications with discovery/topology
and field-conflict fencing. The six-type completeness and conservative chronology
contract documented here remains in force.

Baseline: `ffd8617fa77c484d3f944c97c494dba94269a7f1` (v1.0.22).
Branch: `fix/native-arbitration-evidence-contract`.
No Home Assistant connection, physical command, deployment, release or merge is
part of this review. Physical commissioning remains required after human review.

## Finding

Truthful per-field observation chronology existed, but the native read contract
was selected by the lifecycle caller. Accepted thermal steps, Spa startup,
filtration and Reset requested a permissive four-type read; owned thermal,
shared safety and cleanup requested a validated six-type read. Consequently a
successful verification refresh could leave sibling circuit/source/topology
evidence stale or accept a partial reply. A later phase required those facts
together, after a newer receipt or entitlement boundary. Fresh Pool STATUS did
not imply fresh Spa STATUS, HEATER, PMPCIRC or shared-circuit STATUS.

This explains the failure family without relaxing chronology: when truthful
per-field clocks replaced publication-time freshness, cached sibling fields no
longer acquired freshness through unrelated callbacks. More rereads were needed,
but separate callers disagreed about what a successful reread meant.

The complete unchanged cleanup batch already works on v1.0.22. The positive
controls deliberately pass there. This audit does **not** claim a newly observed
v1.0.22 physical failure, or that an incomplete batch occurred in today's live
installation. It proves remaining repository-level contract gaps and restart
failures. Native packet timing and completeness still need physical confirmation.

## Relevant history

The protected historical behavior is the previously commissioned Pool Solar
startup/target-down shutdown/target-up reacquisition and overnight filtration,
reported by the operator and reflected in existing lifecycle tests. Repository
handoff records physical Pool Solar delivery at v1.0.5 and Reset-to-idle at
v1.0.7, as well as subsequent evidence liveness defects. Neither an integration
load nor a green release proves a complete physically successful Spa restart.
The exact comparison baseline here is v1.0.22, not a claim that this release is
the last fully commissioned known-good system. The regression window is the
transition from publication-time freshness to truthful per-field chronology and
the subsequent caller-specific rereads through v1.0.22, traced below.

| Commit / release | Intended improvement | Remaining boundary |
| --- | --- | --- |
| `6ee18f1`, PR #389 | Truthful per-concept timestamps, immutable observation composition, accepted-command consequence admission | A republished cached field cannot count as a new read; active native rereads must supply the required facts. |
| `3c9275d`, PR #391 | Shared hydraulic reobservation | Separate lifecycle entry points still requested different native sets. |
| `0b03c69`, Reset baseline read; `f5553ba`, filtration verification read | Obtain native observations after physical delivery | Both reused the smaller permissive read. |
| `e0aff10`, v1.0.17 lineage | Full shared-hydraulic refresh for owned thermal sessions | Expanded only the owned-session path. |
| `8001b7a`, PR #429, v1.0.18; `403e7bd`, PR #431, v1.0.19 | Preserve positively PoolOS-originated Spa residuals through Pool priority return and permit their reviewed cleanup/handoff | User/adopted Spa remains excluded; the current candidate retains those gates and tests the fresh-process origin path missing from in-memory handoffs. |
| `ebba088`, PR #433, v1.0.20 | Export/restore fully verified PoolOS-started Hot Tub Solar checkpoints | Manager fixtures supplied matching purpose vocabularies and a warm assessment; a fresh HA policy/driver composition was not proven. |
| `a58010e` / `4b26f90`, PR #435, v1.0.21 | Repeat cleanup reads every 15 seconds and cancel on boundary changes | Cadence improved; WHAT remained caller-selected. |
| `d55481c`, PR #437, v1.0.22 | Complete cleanup batches advance unchanged BODY/source/circuit evidence together | Complete cleanup positive controls pass. Smaller callers and duplicate-reply validation remained inconsistent. |

## Native source and currentness matrix

Every row below preserves the authoritative field's timestamp. The complete read
uses one conservative request-start boundary for **returned, validated** fields,
even when their values are unchanged. It does not stamp cached/unreturned facts.
An intervening native publication or discovery-generation change rejects the
originating read. A later NotifyList remains independently authoritative.

| Arbitration concept | Native source | Timestamp / complete-read coverage | Blocking consumers |
| --- | --- | --- | --- |
| Pool active | Pool BODY STATUS | Field clock; BODY query | Ownership, probe, exclusivity, body-Off verification, cleanup, successors |
| Spa active | Spa BODY STATUS | Field clock; same BODY query | Pool exclusivity, Spa origin/purpose, cleanup, restart |
| Actual pump RPM | PUMP RPM | Field clock; PUMP query | Execution verification, shared circulation, shutdown pump-zero |
| Configured Pool/Spa RPM | Resolved PMPCIRC SPEED | Field clock; PMPCIRC query | Pump target/currentness, restart, execution verification |
| Pump assignment/mode | PMPCIRC CIRCUIT, PARENT, SELECT | Returned field clocks plus generation-bound inventory | Equipment identity, supported RPM control; equality is not provenance |
| Selected source | BODY HEATER, with HTMODE context | Separate field clocks; BODY query | Source selection/Off verification, residual capture, source-safe cleanup |
| Heating demand | BODY STATUS/HEATER/HTMODE | Conservative minimum of component clocks | Source/energy-purpose interpretation |
| Solar physical activity | Solar CIRCUIT STATUS | Field clock; CIRCUIT query | SELECTED != ACTIVE, operating RPM, source cleanup/purpose |
| Waterfall/Jets/Slide | Corresponding CIRCUIT STATUS | Field clock; CIRCUIT query | Shared hydraulic safety and successor arbitration |
| Optional circuit absence | Complete discovered inventory | Validated inventory read boundary | Absence cannot be inferred from a partial list |
| Circuit identity | CIRCUIT SNAME/SUBTYP/USE | Returned identity fields; exact object set | Topology mapping and identity safety |
| Pump flow/power/limits | PUMP GPM/PWR/MIN/MAX/MINF/MAXF | Returned fields; required when already supplied by inventory | Pump quality/configuration/compatibility diagnostics |
| Body temperature/targets | BODY LSTTMP/LOTMP/HITMP | Returned BODY field clocks | Trusted water acquisition, target-down/up, Spa acquisition |
| Native sensors | SENSE SOURCE/SUBTYP | Returned field clocks | Collector/water policy; no interpolation or invented observation |
| System service/firmware | SYSTEM SERVICE/VER | Returned field clocks | Native mode/compatibility and inventory context |
| BODY/PUMP/THERMAL provenance | Accepted receipt / verified consequence / typed transfer / reviewed checkpoint | Immutable causal boundaries, never refreshed by a read | Exact domain command permission and eventual body completion |
| External/operator intervention | Canonical trusted operator evidence and classified native events | Original event time, generation and scope | Domain-specific yield; native disagreement alone is not operator intent |
| Grid status | Canonical grid assessment | Current evaluation identity, independent of native reread | Successor and safety authorization |
| Filtration need/debt | Canonical filtration accounting and policy | Current evaluation identity; RUN_NOW distinct from debt | Immediate successor versus deferred idle |
| Source cleanup / pending verification | Existing typed attempt and receipt | Fixed chronology/deadline; Off must satisfy boundary | Capture, transfer, body-Off and pump-zero progression |
| Policy/manual restraint/maintenance | Existing policy/authority providers | Independent revision/opportunity/session scope | Final command gateway and future eligibility |

Command-free orchestration freshness remains 120 seconds; strict command
verification remains 30 seconds. Read completion time does not make a request
started before acceptance capable of verifying that acceptance. Source capture
and circulation arbitration still require observations at/after their retained
boundary, usable topology, current grid/filtration policy, and valid provenance.

This is not a general valve-position proof. Installed native features without a
supported semantic mapping remain subject to existing compatibility/safety
gates. The contract does not invent an observation for unsupported equipment.

## One WHAT contract, lifecycle-owned WHEN

`IndependentIntelliCenterReadOnlyTransport._async_refresh_arbitration_evidence`
serializes the native batch. `_ReadOnlyModelController.refresh_arbitration_evidence`
freezes expected object identities and fields before awaiting replies, requests
PMPCIRC/PUMP/SENSE/BODY/CIRCUIT/SYSTEM, rejects incomplete/duplicate/changed
identities, and applies nothing until the whole originating read is valid.
Existing `_apply_updates` already records unchanged returned fields. The
additional cleanup-only observer was redundant and is removed.

Coordinator lifecycle methods now delegate to this one contract. Existing read
cadences and command deadlines remain unchanged:

| Lifecycle | Read scheduling / exit |
| --- | --- |
| Owned thermal, probe, preparation, stable operation | Existing 15-second owned loop; stops when its lease/pump-session requirement ends |
| Accepted thermal operation and Spa startup | Existing operation/token-bound one-shot; complete contract, followed by owned cadence where applicable |
| Residual entitlement and captured cleanup | Existing immediate + 15-second loop bound to exact residual/cleanup identity; cancels on boundary advance/unload |
| Filtration verification and owned circulation | Existing receipt read and owned loop; now includes source/shared topology |
| Reset baseline verification | Existing bounded verification; same complete native facts |
| Quick restart | Fresh observations and one authority adjudication; Spa may require one preparatory read after a new tracker first establishes circulation; then restored owned loop |
| Idle/shared safety/future acquisition | Existing admission reread when shared evidence is stale; fresh policy reason still required |
| Shutdown coastdown | Cleanup retains its attempt until actual RPM is verified zero; reads cannot retire it on BODY OFF alone |

Read failures return failure and do not create observation timestamps, ownership,
command receipts or pump authority. The serialized batch is six requests, not a
claim that IntelliCenter provides an atomic physical snapshot. Request-start
dating and intervening-publication rejection preserve that distinction.

## Restart defects reproduced and repaired

1. The new driver initially has no Spa origin. Assessment therefore constructed
   an external-user purpose before the manager could validate the checkpoint.
   An armed **typed, fully verified** PoolOS BODY checkpoint now supplies only
   historical origin to command-free assessment. External-change attribution
   still uses the driver's actual origin. No execution is scheduled on that
   restoration frame; denial discards the preview and recomposes ordinary input.
2. The purpose fingerprint contains `solar_preferred`, but the checkpoint's
   requested-mode field uses `Solar Preferred` (Pool similarly `solar_only` versus
   `Solar`). The redundant cross-vocabulary comparison rejected an exact purpose.
   Exact purpose identity and current requested-mode equality remain mandatory.
3. A fresh Spa tracker cannot prove bulk water on its first circulating frame.
   One complete preparatory native read obtains a genuinely later sample before
   the authority attempt. Failure discards the checkpoint; replacement/unload
   cancels or fences the read; the five-minute checkpoint limit is unchanged.
4. A fresh command-free Spa policy tracker now continues an already physically
   active Solar purpose only with positively supplied PoolOS origin and current
   eligibility. User/equality-only sessions do not enter this path. Cap, priority,
   permission and hysteresis remain effective; new inactive starts still qualify.
5. Successful restoration explicitly retains the verified BODY origin in the
   existing driver lifecycle latch, so later residual Spa cleanup retains it.
6. Restart restoration now requires post-checkpoint, nonfuture configured RPM
   and complete usable shared topology as well as BODY/pump/source evidence.
   Stale/mismatched PMPCIRC or active/stale/incomplete shared hydraulics deny it.

The reviewed restoration scope remains fully verified PoolOS-started Pool/Hot
Tub Solar. User/adopted Spa cannot acquire BODY-start proof through this repair.
Historical receipts/generation remain unchanged; no Spa-to-Pool provenance is
transferred. A new Pool session must acquire its own accepted BODY activation.

## Red-before-green evidence and regression coverage

- `test_every_lifecycle_requires_one_complete_unchanged_arbitration_batch`:
  initial baseline matrix **21 failed / 15 passed**. Three smaller lifecycle roles
  lacked circuit chronology and accepted incomplete batches; all roles accepted
  duplicate BODY entries. Full cleanup/owned positive controls already passed.
  Added configured-RPM omissions and cancellation/overlap controls extend it.
- `test_restart_requires_current_configured_pump_and_shared_topology`: initial
  six negative cases all failed because invalid evidence established ownership.
  Old/future observation controls additionally protect the same boundary.
- `test_native_pool_target_down_idle_target_up_and_spa_restart_return` crosses
  the real native controller, coordinator read contract and adapter into real
  policy/orchestration/driver execution. Its restart leg first failed with purpose
  denial, and then, with a fully fresh evaluator, with an untrusted first Spa
  sample. It now uses fresh trackers and verifies the reviewed runtime restore.
- `test_fresh_tracker_preserves_positively_attributed_active_solar_purpose` was
  red with `OPPORTUNISTIC_QUALIFYING`; its five negative controls passed already.
- `test_residual_loop_keeps_complete_evidence_current_beyond_freshness_window`
  spans 180 modeled seconds and twelve complete unchanged reads, verifies all
  required clocks and cancellation, with no command/ownership creation.
- Existing cleanup transport tests retain intervening-notification, partial
  reply, generation-loss and command/entitlement-during-read rejection controls.
- Reset's failed refresh path exposed a separate existing undefined `LOGGER`.
  A failing behavior regression justifies defining the logger. CI Ruff now also
  includes the HA integration so this omission cannot remain hidden there.

The E2E controller model includes native BODY-ON default circulation, actual and
configured RPM verification, source/Solar coupling, BODY-OFF coastdown at 900
RPM, subsequent physical zero, stable repeated reads, deferred idle, and a new
accepted Pool BODY generation. Both final variants require OWNED/CONVERGED and
all three verified provenance concepts. The existing ten-minute Pool Solar
target-satisfaction debounce is preserved, not bypassed or shortened by tests.

## Final pre-publication regression audit

All six coordinator lifecycle entries delegate to the same transport contract.
The retained legacy private transport entry is a forwarding compatibility alias,
not another read definition. Metadata/discovery subscription reads remain separate
because they establish inventory, not successful arbitration reread completeness.
The redundant cleanup-only observation stamping is removed. Lifecycle scheduling
stays separate because receipt, residual and owned-session cancellation boundaries
are different; merging those schedulers would expand the repair unnecessarily.

Evidence admission cannot create provenance, operator intent, cleanup authority
or successor entitlement. Complete contradictory physical facts remain truthful
observations and are denied by the consuming safety/currentness gate. Rejecting
them as if the read did not happen would hide physical reality. Freshness windows,
verification deadlines, accepted-command chronology, source cleanup, final command
gateways and concept-specific domain permissions are unchanged or stricter.

Manual PMPCIRC override protection remains in `tests/test_pump_speed_session.py`:
startup mismatch is an anchor, configured transition requires the existing signal,
purpose/body/OFF boundaries clear the session override, and reconnect cannot
reconstruct it from equality. No pump-session or operator-attribution production
module changes in this candidate. Reset's only production edit defines its missing
error logger; its new epoch, preserved policy/accounting and safe-reduction contracts
remain covered by `tests/test_reset_recovery_lifecycle.py` and existing Reset tests.

TOU protection remains covered by `test_overnight_catchup_window_runs_outstanding_filtration`,
`test_flexible_morning_filtration_defers_to_overnight_catchup_window`, the real
closed-loop `test_off_to_filtration_owned_to_off_is_closed_loop_and_provenance_based`
at 2600 RPM, source-neutralization tests, and accounting restore/live-overlap tests.
No filtration policy, debt ledger, targets or Gas-selection semantics are changed.
The new Pool cycle explicitly verifies no live OWNED lease or residual/cleanup
entitlement throughout idle before independently reacquiring accepted BODY origin.

## Limits and physical acceptance

Software tests prove state-machine behavior under returned complete native
responses; they do not prove real controller response latency, packet ordering,
or every installed object's support for the requested keys. Six-query read load,
full inventory completeness and the conservative start boundary require capture
on the next reviewed physical attempt. No timestamps are widened to mask this.

After eventual merge/release by the operator: establish owned Pool Solar 2900,
lower target below actual water, observe source Off followed by Pool Off and
verified RPM zero, remain idle with deferred filtration debt intact, then raise
target to 90 and observe a fresh accepted Pool generation, required acquisition,
Solar Active and verified 2900/OWNED/CONVERGED. Allow the configured debounce.
On a later qualified Spa day, verify clean Pool completion, independent Spa
Solar2900, reviewed quick restart, then Pool priority causing Spa source/body/
pump cleanup and independent Pool Solar recovery. Check every domain receipt,
generation, per-concept clock and terminal pump-zero verification.

If any checkpoint fails, stop commissioning, preserve native responses and
ownership diagnostics, and restore ordinary Pool operation through the reviewed
operator procedure. Do not turn the live installation into another patch loop.
