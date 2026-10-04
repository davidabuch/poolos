# Systemic arbitration currentness recovery

Baseline: v1.0.24, `dc67ad4b8fdf769287a5b83e7b4bfda965ad5953`.
Scope: repository repair and green PR. No HA access, equipment operation,
deployment, release, merge, or change to the operator's quarantined Thermal gate.

## Causal finding and evidence limits

The shared six-type API did not guarantee evidence progress. The transport
required `latest_snapshot is originating_snapshot` throughout a read. Any native
callback replaced that pointer, including unchanged RPM or temperature telemetry.
The controller then returned before reading the remaining types. Unchanged BODY,
source and shared-circuit clocks stayed old even though transport health and motor
telemetry were good. Every lifecycle used the same API and inherited this defect.
Adding more caller-specific loops could not make an invalidated read complete.

The original pointer fence dates to `677776fc` in the v0.11.60 recovery lineage;
`6ee18f18` retained it in the accepted-command chronology repair. `d55481c`
expanded cleanup, and PR #439 (`98cac4cf`) consolidated six callers, completeness
and field clocks, but retained the fence. That fence protected a real invariant:
an old reply must not overwrite an intervening topology/source consequence. Its
implementation also rejected harmless publications. This repair preserves the
invariant with field conflict and frozen topology validation.

The previously commissioned Pool Solar, target-down/up, overnight filtration and
manual sessions are the behavioral baseline. No release is asserted to be a fully
commissioned opportunistic-Spa baseline. v1.0.24 independently passed HA-stop and
external-Spa restart commissioning; PR #442's teardown is unchanged here.

The software reproductions demonstrate a sufficient causal mechanism for both
reported failure shapes. They do **not** prove which actual live packets interrupted
the reads; that requires physical trace capture. The filtration stable reproduction
ends SUSPENDED/Pool ON with debt zero. A second pending-step reproduction produces
the reported `PREEMPTED/shared_hydraulic_unusable:waterfall.active` and loses the
lease, leading to re-enable required. Do not conflate those two execution phases.
The probe reproduction accepts BODY and pump operations, verifies BODY and reaches
physical 1500, then times out verifying the pending pump step on the baseline. It
does not falsely claim that a fully verified pump step became unverified in the
physical trace. After repair, the same regression continues through settled water,
typed Solar successor, stable owned Solar2900, target satisfaction, source Off,
Pool Off, pump zero and retired residual/cleanup with no re-enable requirement.

### Red evidence

Before production edits, the three compatible callback cases and both native
lifecycle regressions failed (5 failures): reads stopped after PMPCIRC/PUMP;
filtration remained ON after SATISFIED; probe ended CLEANUP_WAITING with a
RELINQUISHED lease. The probe's retirement is
`runtime_ownership_relinquished:thermal_hydraulic_reobservation_timed_out`.
The separate pending-filtration gap was red with PREEMPTED rather than
AWAITING_REOBSERVATION. After the first field-conflict repair, the adversarial
measurement tests were also red: changing SOURCE/LSTTMP/PWR still starved sibling
topology. All are permanent regressions in
`tests/test_systemic_arbitration_currentness.py`.

## One evidence contract

`NativeArbitrationEvidence` is an immutable read record: monotonically numbered
read ID within this transport, discovery generation, read start/completion,
frozen object/field set, topology identity, and completion/failure. It is carried
in the immutable native transport capture and compact transport diagnostics.
It contains no BODY/PUMP/THERMAL owner, receipt, cleanup grant, intent or entitlement.
Its temporal admission uses the existing shared strictly-post-boundary helper;
it is never sufficient for a command or ownership decision.

Every lifecycle alias enters the same serialized PMPCIRC/PUMP/SENSE/BODY/CIRCUIT/
SYSTEM contract. Freeze identities and required returned fields before awaiting.
Collect all replies without applying them. Missing/duplicate/wrong objects,
changed parent/body assignment/select/name/subtype/use, disconnect or discovery
change reject the read. Validate all fields against intervening native facts
before applying any batch fields. A contradictory newer BODY STATUS/HEATER/HTMODE,
PUMP STATUS/RPM/GPM/limits, PMPCIRC assignment/target, CIRCUIT STATUS or SYSTEM
SERVICE rejects the batch and preserves the separately published newer fact.

Compatible callbacks do not reject it. Newer measurement/policy fields (for
example SOURCE, LSTTMP, power, target) retain their actual received value and clock;
the older returned field is not applied or re-stamped. Unchanged returned sibling
facts advance at the conservative request start. Existing per-field admission
keeps newer clocks even for matching values. These clocks share a conservative
lower bound, not necessarily exact timestamp equality. No cached/unreturned value
acquires a timestamp. A six-request capture is not an atomic Pentair sample.

Cancellation records failure and releases serialization; it publishes no completed
generation. Read-start remains the consequence boundary even when completion is
later than a command, Reset or entitlement. A read never moves a fixed receipt
deadline. The current task registry and STOP fences remain responsible for awaits.

### Producer and consumer inventory

All field observations originate in `_ReadOnlyModelController._apply_updates`:
actual Notify receipt or the specific GetParamList request start. The transport
copies raw field clocks; `NativeIntelliCenterReadAdapter` maps them; coordinator
captures native model/configuration immutably. Publication/evaluation time cannot
refresh a fact. No policy, ownership manager or entity advances a native clock.

| Fact / native field | Capture and identity | Consumers / boundary |
| --- | --- | --- |
| Pool/Spa BODY STATUS | `NativeBodyState.active`; raw attribute clock; exact B1101/B1102 and discovery | Orchestration, ownership, probe, pump session, source/cleanup, circulation, filtration, Reset, restart. Accepted BODY and cleanup receipts require later facts; matching state supplies no origin. |
| PUMP STATUS/RPM/GPM | `NativePumpState`, raw field clocks; resolved parent | Actual motor/flow verification, probe, live/cleanup, filtration, circulation, Reset/restart. Strict receipt chronology; actual RPM does not identify an operator. |
| PUMP power and limits | PWR/MIN/MAX/MINF/MAXF; separate returned clocks | Diagnostics, native capability/configuration and final target bounds. Power changes do not invalidate topology; contradictory limits do. |
| Pool/Spa configured target | PMPCIRC SPEED/SELECT; body-specific resolved circuit and parent | Pump session, manual PMPCIRC intent, live and filtration verification, restart/currentness. Configured and actual are separate. Startup anchors do not create intent. |
| PMPCIRC topology | CIRCUIT/SELECT/PARENT; frozen assignment | Dynamic resolution, physical authority, pump sessions, currentness, restart. Wrong body/mapping cannot cross generations. |
| Selected source / heating context | BODY HEATER/HTMODE; independently dated attributes | Requested/selected/active policy, execution, ownership, source cleanup, termination, circulation, restart/Reset. H0002 is not Solar Active. |
| Solar physical activity | Solar CIRCUIT STATUS | Thermal purpose, engagement, operating RPM, pump session, cleanup, successors. Native environmental disengagement is not operator intent. |
| Waterfall/Jets/Slide and other mapped circuits | CIRCUIT STATUS plus names/subtype/use; exact inventory | Shared hydraulic classification in orchestration/ownership/live execution/circulation/filtration/final authority. Active conflicts still deny commands. Nonconflicting pool-light classification is unchanged. |
| Optional circuit absence | Complete inventory and inventory read-start | Adapter absence mapping and shared-safety completeness; partial inventory cannot prove OFF/absence. |
| Controller/service mode | SYSTEM SERVICE/VER | Native compatibility and physical gateway. Unsafe mode remains a global deny; rereads cannot override it. |
| Temperature / native target | SENSE SOURCE/SUBTYP; BODY LSTTMP/LOTMP/HITMP | Water stabilization, Pool/Spa policy and current targets. A newer real sample/target wins without renewing cached topology. |
| Source cleanup state | Typed source attempt plus BODY source observations | Fixed accepted source-Off boundary, verified reduction and cleanup capture. Solar inactivity is not selected-Off proof. |
| BODY/PUMP/THERMAL origin | Accepted receipt, causal verification, typed transfer or reviewed checkpoint/adoption | Exact domain/purpose/generation gates, residual creation and eventual completion. Native reads never refresh receipts. |
| Grid, debt/TOU, maintenance, operator evidence | Existing independent canonical providers | Current policy/authority frame and final gateway. Not supplied by a Pentair read; no debt mutation, intent fabrication or switch enabling. |

The detailed native object map also remains in
`NATIVE_ARBITRATION_EVIDENCE_AUDIT.md`. The old audit's blanket intervening-publication
rejection is superseded only by the field-aware admission described here.

### Consumer chronology is explicit, not interchangeable

The existing shared `evidence_chronology` decides pre/equal/post acceptance.
Consumers use each returned field's truthful timestamp and typed currentness.
The read record explains composition/completeness; it cannot substitute for a
domain's newer physical fact, required value, quality or boundary.
Steady orchestration/ownership allows the established 120 seconds. Strict physical
verification allows 30 seconds and strictly later accepted consequences. Residual/
cleanup also applies its exact retained entitlement boundary. These differences
are deliberate requirements, not permission for differing read sets or fabricated
publication clocks. No interval or command deadline is increased in this repair.
The read record's `admits_boundary` is only temporal admission, not freshness or
physical usability; complete contradictory hardware remains visible and blocked.

## Every lifecycle and recovery owner

All native rows use the same complete read. WHEN remains lifecycle-specific
because a receipt, residual, steady lease, checkpoint and Reset have different
cancellation/authority boundaries. Different WHEN is not a different WHAT.

| Stage | Boundary / evidence requirement | Existing consumer and reread owner |
| --- | --- | --- |
| 1 Cold Pool start | Current reason, idle exclusive topology; then BODY acceptance | thermal driver; shared admission and accepted-step read |
| 2 Pool probe start | BODY and 1500 receipts; later BODY/PMPCIRC/actual | thermal live/automatic; accepted and owned loop |
| 3 Probe stabilization | Fresh advancing water samples and hydraulic continuity; fixed acquisition interval | water-temperature tracker; owned loop |
| 4 Probe to ordinary | Exact typed compatible successor; source safe | orchestrator/driver; owned/cleanup reads |
| 5 Probe to Solar | Trusted water and eligible source; typed body continuity | orchestrator/live; accepted/owned reads |
| 6 Ordinary Pool | Current body/pump session and topology | filtration/pump runtime; owned loop |
| 7 Solar engagement | Selected receipt verification distinct from physical engagement; fixed bound | thermal live/driver; accepted/owned reads |
| 8 Stable Solar | Existing domain origin, current facts and intent | ownership manager; owned loop |
| 9 Solar to filtration | Verified source Off; RUN_NOW and typed circulation transfer | termination/circulation/filtration; cleanup then owned |
| 10 Solar to OFF | Residual source/body/pump chronology; no successor | cleanup/circulation; residual/cleanup loop |
| 11 Target satisfied | Existing target debounce and safe source reduction | thermal policy/termination; owned then cleanup |
| 12 Target down | Policy revision, no manual owner fabrication | same target/termination path |
| 13 Target up | New independent purpose after idle; no reuse of old command | fresh assessment/admission, then accepted/owned |
| 14 TOU filtration start | Current debt/window; fresh topology; BODY then pump receipts | filtration driver; accepted read and pending/owned loop |
| 15 Stable TOU | Verified lease, current 2600/configured/shared evidence | registry/filtration; owned loop |
| 16 TOU debt zero | Canonical accounting, no successor, retain BODY origin | filtration; owned/accepted cleanup read |
| 17 Filtration OFF | BODY Off AND actual pump zero after acceptance | filtration verifier; pending/owned loop |
| 18 Filtration to Solar | Exact registry transfer, stale/acquiring lease cannot transfer | typed handoff; thermal accepted/owned |
| 19 Solar to filtration | New pump purpose; preserve only valid compatible BODY | typed handoff; cleanup/filtration owned |
| 20 Pool to manual Spa | Positive request affects body; no cross-body origin | external-change/manual, Spa policy; startup/owned reads |
| 21 External Spa execution | User origin is not accepted PoolOS BODY activation | Spa assessment/driver; existing pump/source scope |
| 22 Opportunistic Spa start | Independent qualified opportunity; source precondition then BODY receipt | Spa policy/driver; startup/accepted/owned |
| 23 Spa source transitions | Selected versus active, purpose and domain intent | Spa/pump policy; owned/accepted |
| 24 Spa shutdown | PoolOS-created body origin or reviewed completion scope; no autonomous Gas fallback | source/cleanup/circulation; residual loop |
| 25 Spa to Pool | Spa verified cleanup; separate fresh Pool activation generation | cleanup then independent Pool admission |
| 26 Residual cleanup | Exact entitlement/cleanup token; post-token source/body/shared facts | termination/cleanup/circulation; periodic residual loop |
| 27 Reset | New authority epoch, current safe-baseline proof, old commands fenced | button/final authority; Reset complete reread; quarantine stays disabled |
| 28 Pool restart | Exact fully verified checkpoint scope or independently justified prospective adoption | restart preparation and one adjudication; then owned loop |
| 29 PoolOS Spa restart | Reviewed fully verified PoolOS BODY checkpoint only | restart preparation/adjudication; then owned loop |
| 30 External Spa restart | No BODY activation reconstructed from equality | fresh assessment; no PoolOS BODY checkpoint |
| 31 Manual pump | Positive configured PMPCIRC transition/current session; startup anchor excluded | pump-speed session; existing generation/verification rules |
| 32 Manual Thermal | Positive scoped source intent; independent BODY/PUMP | canonical external-change/domain evidence; owned reads do not erase it |
| 33 Operator BODY Off | Current positive request/canceled semantic opportunity | manual/external evidence; old accepted continuation fenced |
| 34 Grid preempt/return | Higher safety authority and fresh policy on return | grid runtime/final gateway; native evidence cannot clear grid authority |
| 35 Delayed/unknown transport | No fabricated timestamp; retain responsibility while proof unavailable | same batch rejects/diagnoses; existing bounded verifier/recovery owns next step |
| 36 Startup RPM/valves | Accepted BODY origin plus required topology/actual convergence; no intent inferred | live/pump sessions; accepted/owned rereads |

## Recovery and concurrency audit

Filtration's pending step previously escalated missing evidence to PREEMPTED,
released its lease and latched re-enable. Verified filtration already suspended
and retained cleanup responsibility. Pending acquisition now waits command-free
with the exact attempt/deadline; usable later facts verify it normally. Exhaustion
is a control fault, with independently verified BODY responsibility preserved by
the existing `_fail(failed_domain=...)` path. It is not operator takeover.

The existing filtration keepalive now also runs while a lease has an accepted
verification token. Previously the first one-shot failure had no retry owner until
the lease was fully verified. The driver removes the token on verification,
failure, preemption/unload; the existing cadence is unchanged. No command is
retried by this observation loop. Thermal already keeps accepted OWNED leases
observed. Cleanup already retains its exact token and repeats; no new polling
system, generic StopPump, or second ownership store is introduced.

| Condition | Authority/permission and exit |
| --- | --- |
| Transport absent or complete read failed | No field renewal; command-free wait/read while current lifecycle exists. Original receipt deadline remains fixed. |
| Complete read, consequence not converged | Current evidence reaches existing causal verifier/hold; finite verification/convergence fault if exhausted. |
| Shared facts aged | Same complete read refreshes genuinely returned unchanged fields; verified filtration suspension resumes when proof returns; pending filtration retains its attempt. |
| Current operator/safety/topology contradiction | Existing positive scoped intent, safety and final authority checks still win; read success grants no authority. |
| Generation/topology identity changes | Originating batch discarded. New discovery rebaselines; old receipts/checkpoints obey their existing restore contract. |
| Rejected physical command | Existing explicit delivery fault; no fabricated External owner and no blind replay. |

Retained legacy read entry points are forwarding aliases only. Discovery and BODY
target-metadata reads are principled exceptions: they discover inventory/synchronize
policy, not certify a complete arbitration generation. The six lifecycle coordinator
wrappers and single native serializer remain one read definition. One-shot accepted,
steady-owned and exact-residual schedulers have different exit tokens and are not
redundant. Shutdown's task registry awaits all of them. Combining their authority
lifetimes would be unsafe. No cleanup-only timestamp workaround remains.

Serialization prevents interleaved batch application. A canceled owner releases
the lock without publishing a successful read; another caller can continue. A
read begun before a newer receipt/Reset cannot verify that work. Old task callbacks
cannot acquire authority from read completion. Queue/read latency remains physical
uncertainty; a read taking longer than strict freshness must fail closed. Fixed
deadlines and correction budgets are not renewed to compensate for it.

## Regression and hostile prediction matrix

`ownership/systemic_currentness_prediction_matrix.json` contains all requested
A–BJ cases with exact accepted text and real test-function references. Its integrity
test rejects omitted IDs or references to nonexistent tests. These are mechanism
and lifecycle assertions, not a claim of physical commissioning or all 90 scenarios.

New native callback tests cover both failure shapes, hot Spa water flush, compatible
same-value callbacks, newer measurements, contradictory domains, missing/duplicate/
wrong-generation/identity control reuse, cancellation, strict read-start versus
completion, pending-filtration recovery/deadline and disabled Reset gate. The real
native E2E test now runs Pool target-down/idle/target-up and reviewed Spa restart/
Pool-priority return both with and without callbacks during complete reads.
Existing source-Off, TOU accounting, domain/operator, semantic opportunity,
checkpoint-negative and PR #442 STOP suites remain behavioral gates.

The extended probe's shutdown control explicitly has no immediate filtration
successor. Its initial version used the helper's nonzero default obligation and
correctly retained circulation for filtration; setting that test policy to zero
tests the requested no-successor shutdown without changing production policy.

Global invariants checked across these transitions: no orphan after current
shutdown proof; BODY Off is not completion until pump zero; unknown is not an
External owner; stale evidence cannot verify/adopt; old generation/deadline cannot
act on successor; accepted work has verified/wait/fault/preemption exits; pending
wait retains a named owner/deadline; successful fresh proof clears the evidence
blocker; domain origin is independent of the other two domains. The property
matrix does not grant authority or claim general fault replay/adoption scope.

Two older transport positive fixtures changed PMPCIRC assignment or SENSE subtype
inside what they called an unchanged read. They now establish those same identities
at discovery. Their command/RPM assertions remain unchanged; topology-negative
tests are stronger. No ownership/currentness assertion was deleted or relaxed.

## Physical acceptance after independent review and eventual release

Still unproven: actual read latency/packet cadence/completeness, installed-object
support, and whole physical lifecycles. Record compact read ID, discovery generation,
start/completion/failure, current domain origin, pending receipt/deadline and blocked
concept. Correlate those with raw packet chronology; do not assume a Pentair SLA.

1. Current quarantine/manual fallback remains untouched during repository work.
2. Under separately authorized commissioning, establish owned Pool Solar 2900.
3. Lower target below water; observe debounce, verified source Off, Pool Off,
   actual zero, clean idle and preserved TOU debt.
4. Raise target; acquire a distinct legitimate Pool generation, probe1500 if
   required, stable trusted water, selected/physically active Solar and 2900.
5. Let TOU debt run at2600 through SATISFIED and verified Pool Off/pump zero.
6. On a qualified Spa day, verify Pool completion, independent opportunistic Spa,
   Solar2900/no Gas, allowed short checkpoint restart, Pool demand return, Spa
   source/body cleanup and independent Pool Solar reacquisition.
7. Recheck external Spa restart and task quiescence without stealing user BODY.

At any failed checkpoint, stop commissioning, preserve read/receipt/generation
evidence, and use the reviewed operator fallback. No live patch, Reset merely to
erase evidence, freshness extension, or speculative equipment command follows.

## Independent-review follow-up: persistent intent and external credit

The original internal Reset-gate test missed the HA service/RestoreEntity awaits.
The new HA-facing regression reproduces this reachable sequence: switch
`async_added_to_hass()` awaits old ON; actual `async_turn_off()` and Reset button
`async_press()` complete; old restore calls `thermal_automatic_runtime.set_enabled(True)`.
Reset itself never calls enable; the only other ON caller is the explicit ON
service. Recorder state timestamps cannot prove which caller ran live or exclude
an automation/reload. No HA was accessed to invent that missing context.

One persistent-switch bootstrap mechanism covers Automatic Thermal/Filtration,
Thermal Live, Grid Safety, Maintenance and Pool/Spa autonomous-control switches.
RestoreEntity registration/persistence remains. Explicit services record intent
before gate mutation. Pending restore/re-add cannot overwrite that resolved
choice. Bootstrap is admitted once per runtime. Config reload carries only
explicit operator choices, without cached physical checkpoint attributes even
when the old state bit agrees. A red OFF→ON/reload regression proves that a
pre-OFF checkpoint cannot be rearmed. Process
restart still restores durable HA state and desired ON passes existing fresh
execution gates. Reset does not clear gate intent: it changes authority/session
state and existing session restraints, not durable policy. This map holds no
physical state, receipts or ownership. Sibling races were reproduced red for
filtration/live/grid; paired ON/OFF controls also cover Maintenance and Pool/Spa.

An additional pair of actual Reset regressions was red: Reset directly resumed
Pool/Spa autonomous-control switches despite persistent operator OFF. The button
now retains OPERATOR_RESTRAINT/RESTORED policy gates while clearing the existing
transient manual/native BODY-session sources. Paired controls prove those transient
cancellations still clear. Reset reduction, debt and safe-baseline proof are unchanged.

Accounting already prioritizes CREDITING when physical routing qualifies, even
during higher-priority Solar, and requires no command ownership. Do not remove
`DEFERRED_HIGHER_PRIORITY` to repair missing proof. The native-boundary regression
instead reproduces frozen credit: manual Pool/Solar2600 and motor callbacks
continue, unchanged BODY/source facts age, and with execution disabled no owned
loop rereads them. Existing coordinator reconciliation now requests the same
complete read while circulation is present. No new timer, command loop or
ownership boundary is added. Failed reads leave old facts old.

Two adversarial qualification tests were also red: native STATUS/temperature may
share a BODY source ID, so stale temperature poisoned separately current STATUS;
and GOOD critical facts had no independent timestamp check when aggregate health
omitted their stale source. Live and replay now check exact field quality/time
against canonical native steady freshness120s. Unrelated sibling staleness cannot
poison native proof; stale/future/missing critical fields still reject credit.
Legacy non-native source-health markers remain required. Diagnostics expose
unusable credit concepts separately from the RPM factor.

This demonstrates a sufficient software cause for full RPM factor/no credit.
The exact live rejected concept needs same-time values/quality/clocks/stale
sources. HEALTHY is not filtration-specific proof. The tests do not reconstruct
the recorded packet stream or establish physical commissioning.

Tests cover actual OFF/Reset/post-close refresh/state publication, arbitrarily
delayed old restore/re-add, durable ON/OFF restart, actual setup intent-handover
statements on reload, Reset preserving ON without enable, a native manual-Solar
hour, partial debt, full satisfaction preventing an actual later TOU BODY command,
and remaining debt permitting fresh TOU acquisition. Route/RPM negatives, exact
field freshness, shared-source isolation and history/duplicate/older controls are
command-free. Existing prospective adoption tests preserve historical manual
origin; credit creates no receipt or shutdown authority. Unseen restart gaps are
not credited. Source/purpose labels cannot double-count a ledger interval.

Prediction coverage is now A–CJ (88 cases). Original native generation/topology
fencing, fixed deadlines and PR #442 STOP remain intact. Physical checkpoints add
Thermal OFF → Reset → delayed refresh/reload → still OFF, and external
Pool/Solar2600 → advancing credit → satisfied/no later TOU or debt/fresh TOU.
No live switch, fallback, target or equipment was altered.
