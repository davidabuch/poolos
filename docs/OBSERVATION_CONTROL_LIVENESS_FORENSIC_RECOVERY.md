# Observation/control liveness forensic recovery

## Evidence and scope

Baseline: current main v1.0.28, `6329d0bfcbcf733d1bf01f336510de998aeb7480`.
Historical reference: v0.11.88, `99d5585caaf837ec81a5b6cb5951895cc5d7dedc`.
This is repository archaeology plus deterministic differential evidence, not a
reconstruction of all deployed packets or certification of a physical release.
No HA, equipment, targets, live gates, reset or production session was accessed.
The parked external Pool2600 catch-up session is outside this engineering work.

Read governance: AGENTS.md, development handoff, accepted ownership and pump
contracts, workflow v2, ADR-005/087/095/096/104/110/111, and prior recovery audits.
Historical milestone assertions such as ADR-005's never-restored Safety switch
are superseded by #339's explicit desired-gate persistence; they do not override
current ownership/safety contracts. No safety policy is reverted here.

The machine-readable companion `ownership/observation_control_liveness_history.json`
records exact peeled release commits, first-parent changes, traced-boundary diff
inventory, and executable references for all 30 requested behavioral classes.
Annotated tag object IDs are not release commit IDs. The missing local v0.11.92
name is represented by the supplied release merge commit, which exists in history.

## Strongest historical anchor

PR #339's original description explicitly says **successful v0.11.87 grid-outage
commissioning**. v0.11.87 is `16997a07dda7d05329870eaf3d1a965d66145315`;
#339 is `430fd0a6f20e510424385fb0d518e374fd590e98`. v0.11.88 packages that
hardening: desired Safety gate persists across HA restart; the final gateway
adds a global confirmed-outage pump ceiling. This is the strongest reference for
recovering the user's previously functioning controller plus its final outage
hardening. It is **not proof that v0.11.88 was flawless or physically ran every
scenario**. The successful physical outage statement names v0.11.87, not .88.

There is insufficient repository evidence to promote .89–.96 into a wholly
commissioned last-good controller. Useful scheduling/UI and suppression fixes
landed there, and later PRs explicitly document live manual-session failures.
v0.11.104 proves loaded scoped-live runtime/gates after restart, not a new complete
unattended day. Preserve those useful fixes; do not deploy a synthetic old binary.
The evidence supports .88 as a reference hypothesis, with .87 as the explicit
outage commissioning anchor, rather than an exact proven final-good-day boundary.

## Release-by-release reconstruction

Before .84, mapped HA events, native callbacks, periodic coordinator reconciliation,
recorder, parity and asynchronous analysis already coexisted. Native control had
been authoritative since `631387cb` (August20), before the outage window.

| Release / merge | Before → change / replacement | Responsibility/equivalence and evidence |
|---|---|---|
| .84 `54f0a05` / #331 `7a529dd` | Outage reduction → owned Pool completion when filtration satisfied | Adds observation-edge outage termination handoff; BODY provenance required. Not observer removal. |
| .85 `ecb0415` / #333 `4be1231` | Outage preemption → capture shutdown entitlement before loss | Repairs capture ordering in outage runtime, not observation source/timer. |
| .86 `e4f65d6` / #335 `23853b4` | Entitlement capture → observation-edge capture | Repairs chronology of residual ownership; source facts still shared-clock native. |
| .87 `16997a0` / #337 `7aafe57` | Local termination proof → exact residual BODY proof | Live outage commissioning subsequently documented by #339. |
| .88 `99d5585` / #339 `430fd0a` | Volatile Safety switch → RestoreEntity; local limits → central outage ceiling | Legitimate safety hardening. Direct observer remains; no native tracker. |
| .89 `a6a5071` / #341 | One filtration schedule → configurable profiles | Scheduling/accounting policy inputs expanded; source/publication machinery retained. |
| .90 `303c331` / #343 | Filtration settings → conditional time controls | UI/options; no observer/listener removal. |
| .91 `45709fb` / #345 | Conditional settings → restored time controls | UI regression correction; same native observation path. |
| .92 `d75a5eb` / #347 | Controls → settings panel bootstrap | UI publication; no replacement of observation cadence. |
| .93 `30399d3` / #349 | Sticky manual OFF → independent opportunity retirement | Legitimate suppression/liveness repair, not equality ownership. |
| .94 `84c7afd` / #351 | Transient OFF reflected as disabled → distinct persistent switch; ordinary pump policy | Live manual Pool ON normalization gap documented in #353. Full behavioral equivalence not demonstrated. |
| .95 `1747472` / #353 `fa728e7` | Native diagnostic events → conditional immediate thermal refresh plus native filtration frame | Adds execution wakeup; still depends on diagnostic event presence. Live no-event case later disproves equivalence. |
| .96 `90d3e19` / #355 | Diagnostic Pool ON → suppression retirement | New session handback still event-dependent. Live case leads to #357. |
| .97 `7cad1ba` / #357 `a5ea8ff` | Diagnostic-event retirement → authoritative BODY boundary helper | `21c842d` binds helper; `a729435`/`fc1e463` correct wiring. Retires transient restraint only, not durable gate or BODY ownership. |
| .98 `a791c94` / #359 `d01e5eb` | Diagnostic wakeup → NativeCirculationChangeTracker (`4857544`); native execution reuse (`030659c`) | Adds direct wakeup independent of diagnostics. Separately broadens filtration to any recent native frame; pre-consequence race later documented in #383. |
| .99 `c20e36e` / #361 `8048e36` | Thermal chronology/diagnostic cost → targeted guards | Observer subscriptions/read cadence retained; not evidence that the mixed-frame substrate is fixed. |
| .100 `eb5ea92` / #363–370 | RPM-only → unit-aware targets/GPM and HA composition | Pump identity/capability/configuration vocabulary changes; shared-clock adapter remains. Keep RPM compatibility. |
| .101 `c4482e9` / #372 | Probe/sanitation → unit-aware targets | No removal of native observer or mapped listener. |
| .102 `e823c37` / #374 | Vendor-coupled capabilities → canonical abstraction | Positive equipment capabilities; no liveness replacement. |
| .103 `d2dc27d` / #376 | Capability policy → commissioned installation composition | Configuration/gateway scope, not freshness renewal. |
| .104 `576b0f5` / #378 `e965f7a` | Historical OBSERVE label/config → actual scoped-live status | Removes `operating_mode` field/default/config, not listeners, native read transport, parity, recorder or runtime observer. |
| 1.0.0 `572088a` / #380–382 | Documentation/metadata cleanup → release | No independent observation/control redesign; inherits .98 mixed-frame risks. |

`030659c` is dated September29 23:12:42 **-0700** in Git, which is
September30 UTC. Both date descriptions refer to the same change.

### Major post-1.0 substrate changes

| Version / repair | Responsibility affected / why local fixes were insufficient |
|---|---|
| 1.0.1 #383 | Accepted filtration BODY_ON fenced against old Pool-OFF before consequence. Fixes a demonstrated .98-era reuse defect; not a general timestamp model. |
| 1.0.2 #385/#387 | Acceptance later than frame time could produce ownership-end-before-start. Guards protect chronology locally while orchestrator conflict processing remains upstream. |
| 1.0.3 #389 `6ee18f18` | Per-field observation times, frozen native/transport input, shared accepted-consequence admission. Removes direct native tracker refresh and filtration alternate-native shortcut. Correctly prevents mixed epochs and old facts destroying new ownership. Also removes implicit shared-clock freshness renewal. |
| 1.0.4 #391 | Real shared-hydraulic read replaces cached OFF evidence. This liveness need became visible when clocks became truthful. |
| 1.0.5 #394/#395 | Reset post-close reevaluation and PMPCIRC identity independent of whole snapshot timestamp. Keeps real per-field proof. |
| 1.0.6 #399 | Receipt-bound genuine reread for accepted thermal steps; no assumed consequence. |
| 1.0.7 #401 | Stable verified thermal sessions gain periodic genuine reads; no pending receipt otherwise owns liveness. |
| 1.0.8 #403 | Reset evaluation generation separated from unchanged evidence identity. |
| 1.0.9–10 #405/#407/#408 | Reset baseline, stable filtration and accepted filtration genuine-read paths. Active/receipt-based scopes leave idle acquisition uncovered. |
| 1.0.11–16 #410/#412/#415/#420/#422/#424/#426 | Spa purpose/residual plan, delivery validator, pump authority and verification chronology. These are real domain/execution corrections, not substitutes for observation production. |
| 1.0.17–20 #427/#429/#431/#433 | Fresh restart evidence, PoolOS Spa origin and reverse handoff, bounded verified Spa checkpoint. Equality remains insufficient. |
| 1.0.21–22 #435 / `d55481c` | Cleanup recurring reads and complete batch chronology. Per-phase read definitions and partial coverage still differ. |
| 1.0.23 #439 | One serialized six-type native arbitration contract; lifecycle schedulers request the same WHAT. Pointer fence still rejects harmless callbacks. |
| 1.0.24 #442 | Integration STOP cancels/awaits all owned work without new equipment commands. |
| 1.0.25 #444 / `677760c` | Compatible native callbacks stop aborting batches; critical contradictions/generation/topology still reject. External active circulation gains reconciliation reads; idle is excluded. Persistent intent and accounting qualification fixed. |
| 1.0.26 #447 | Unknown→known identity hydration; explicit 30-second backstop survives DataUpdateCoordinator event rescheduling. |
| 1.0.27 #450 | Backstop pass timeout, failure recovery and observability. A running task alone does not prove it obtains needed facts. |
| 1.0.28 #453 | Durable observation I/O outside authoritative lock. Fixes serialized publication starvation, including idle. The idle native read is still skipped. |

## What the old observation mechanisms actually did

| Mechanism | Operational responsibility | Current disposition |
|---|---|---|
| Native transport NotifyList/update hook | Capture controller values and initiate fast publication | Still present. Receives sparse/unchanged updates; not a complete topology read. |
| Whole `transport.observed_at` on every canonical concept | Any motor/environment callback implicitly made BODY/source/shared facts current | Removed by #389. This was a hidden liveness contribution but not truthful per-field observation. Never restore this clock rule. |
| Mapped HA `state_changed` listener | External grid/status/policy facts and prompt reevaluation | Still present in coordinator. Native authority cutover preceded outage work by weeks. |
| DataUpdateCoordinator 30s cadence | Periodic recomposition/watchdog | Still configured, but event publication could postpone it. #447 adds independently owned cadence; #450/#453 make it resilient/non-blocking. |
| Direct conditional `thermal_runtime.refresh(publish=True)` in native observer | Bypassed need for diagnostic event and eventual coordinator composition; could recompute native policy using older coordinator evidence | Added #353/#359; removed #389. Replace with coherent composition, not this mixed-epoch shortcut. |
| Alternate filtration native snapshot + native-derived execution ID | Wake filtration immediately even if policy frame old | Added .95, broadened .98; removed #389 after pre-consequence topology regression. Fixed coherent authoritative frame is the replacement. |
| BODY session-boundary helper | Retire only transient OFF restraints on a real new BODY edge | Still present; not removed. No ownership creation. |
| Pump synchronization/operator event observer | Current purpose, generation, positive domain intent before policy; Safety before sanitation/thermal/filtration | Still present; immutable orchestration input now binds native and transport. |
| Recorder/parity/inventory/analysis | Durable forensic/accounting history, diagnostics and commissioning evidence | Still present. Not command owners. #453 removes durable I/O from authoritative lock, not the observer. |
| Historical `operating_mode=OBSERVE` | Product/configuration/diagnostic label | Retired .104; no operational listener or native polling responsibility attached. |

Searches included deleted-file/rename history, `git log -S/-G`, first-parent release
diffs and PR descriptions. No deleted native/HA observer, recorder or parity
program is found in the .88–.104 traced production window. August work
`02c3497` decoupled analysis and `da0286e` published state before persistence;
these predate the outage anchor. The user's sequence is valuable evidence, but
it cannot substitute for the actual changed responsibilities above.

## Root architectural cause and demonstrated boundary

The hidden old contract was: a complete controller *view* could be considered
fresh after any transport update. There was also an immediate direct native
execution wakeup in .95–1.0.2. Neither safely distinguishes observation clocks
from publication, policy frame, or command acceptance. The .98 filtration reuse
adds an independently demonstrated failure: a fresh-enough frame can precede the
accepted BODY_ON consequence and falsely end acquisition.

#389 correctly removed both invalid assumptions. Its replacement must guarantee
(1) timely coherent policy publication, and (2) genuine current facts for all
future/current lifecycle decisions. The first obligation was still vulnerable
to rescheduled reconciliation and durable I/O; #447/#450/#453 now repair those.
The second was implemented piecemeal around active leases/receipts/residuals.
That cannot cover **idle → new independent reason**, where by definition there
is no ownership token or receipt yet. This is not evidence that every subsequent
bug shared one cause, but it explains the demonstrated failure family upstream.

The historical clock differential first diverges at #389/v1.0.3. The .98
pre-consequence filtration divergence is a separate earlier root demonstrated by
existing #383/#389 tests. The latest idle-read omission is directly demonstrated
on v1.0.28: valid canonical initial OFF/0, no lease/residual, repeated 30-second
reconciliation, no callbacks or motor-only callbacks; at150s BODY/source still
have initial clocks; at240s a valid new Pool opportunity delivers no BODY command.

The red log recorded 3 failures / 6 controls: two idle evidence-starvation cases
and a blocked new Pool acquisition. Failure/STOP and historical-clock boundaries
passed before production edits. The historical reference kernel freezes .88's
clock projection on identical returned values; it does **not** execute a second
historical controller or prove all historical decisions. Production imports no
historical runtime. Tests require no Git history/network in CI.

## Repair and complexity review

The coordinator's existing reconciliation pass now attempts the same bounded
canonical arbitration read regardless of physical circulation state. This
restores observation before ownership, including idle, startup/restart and future
opportunity admission. No new timer, subscriber, observer system, freshness policy,
retry command, adoption rule, intent classifier or equipment write is added.
Read failures publish no completed batch and renew no stale facts. Coherent
read-start clocks and generation/topology/contradiction checks remain unchanged.

Delete `_native_circulation_present`: value-based selection of whether to keep
observing was the obsolete coupling. Raw equipment OFF is not a reason to stop
collecting evidence for future autonomous policy. The disconnected/no-transport
boundary is already owned by `_async_refresh_native_runtime_evidence`, so it need
not be duplicated in each lifecycle or inferred from RPM.

Do not delete receipt/residual/checkpoint/owned-session reads simply because a
steady backstop exists. Those bind strict post-acceptance clocks, shorter deadlines,
and per-generation cancellation; a30s steady pass does not replace a15s strict
verification owner. No unproven scheduler consolidation is included. The unused
legacy circulation tracker module remains as tested historical mechanism evidence,
not a live production observer. Safety/currentness/execution modules are deliberately
unchanged. Grid is authoritative external HA evidence; a native batch cannot renew
it or remove an outage fence.

The existing native lifecycle simulation now calls the **production coordinator
reconciliation entrypoint**, replacing unconditional test-side read admission.
It covers Pool Solar2900, target-down/source-Off/BODY-Off/nonzero coastdown/zero,
quiet idle180s, target-up new generation, and optional independent Spa Solar,
verified short checkpoint restart, provenance-bound Spa cleanup/Pool priority.
It still models native default BODY-start RPM, exact accepted command provenance,
causal verification and no autonomous opportunistic Gas. Test stubs do not model
all real HA/Pentair latency; explicit coverage limits remain.

All30 behavioral classes map to executable tests. Existing tests protect probe
flush, immediate/deferred filtration, manual credit, domain independence,
operator OFF, external Spa/Gas, Reset/quarantine, restart, confirmed outage/global
ceiling, grid return, reordered events and live shared-circuit contradictions.
A matrix reference is traceability, not a claim that each scenario is one complete
physical-day test or that all90 ownership scenarios are implemented.

## Physical acceptance still required

Repository evidence proves the idle-read omission and its repair in a real
transport/adapter/coordinator boundary, including command-free partial/disconnected
and STOP controls. It does not prove which live packet first caused every reported
historical failure. The whole .88 last-good-day hypothesis still depends on retained
physical commissioning evidence; do not turn it into a source-only certainty.

After independent review/eventual separately authorized release:

1. Keep quarantine/manual catch-up untouched until commissioning is authorized.
2. Long quiet idle beyond120s; verify full read IDs/field clocks/generation continue.
3. Morning Pool demand → BODY accepted → probe1500/flush/trusted bulk water →
   selected and physically active Solar → owned2900.
4. Target down → source verified Off → Pool Off → actual pump0 → idle; debt intact.
5. Quiet idle beyond120s → target up → fresh Pool generation/Solar2900, no Reset.
6. Natural midday/evening Solar loss and immediate/deferred filtration successors.
7. TOU2600 → exact debt satisfaction → verified Pool Off/pump0; manual circulation
   credit must not gain BODY ownership or trigger redundant later TOU activation.
8. External Spa/Gas3000, explicit OFF and restart origin remain externally initiated.
9. On qualified roof conditions only: fresh opportunistic Spa Solar2900/no Gas →
   reviewed short restart → Pool demand return → Spa cleanup → independent Pool.
10. Recheck confirmed outage reduction/global ceiling, satisfied-owned shutdown,
    authoritative grid return/new evaluation, genuine accessories and operator races.

Collect read start/completion/failure and generation/topology identity, per-field
clocks, coordinator attempts/success/trigger, fixed receipt deadlines and origin
for each checkpoint. If any fails, stop, preserve evidence and use reviewed
operator fallback. No immediate live patch or Reset to erase evidence.

## Candidate validation and adversarial review

- New differential/idle acquisition/partial/disconnected/STOP/matrix tests:10 passed.
- Focused executable30-class matrix plus native, domain, grid, pump, Reset and
  shutdown suites:855 passed.
- Full exact tracked-plus-candidate tree:3956 passed; one existing duplicate ZIP
  warning. Ignored Finder metadata was excluded without deleting user files.
- Ruff including the custom integration/IntelliCenter/scripts, MyPy225 source
  files, compileall and diff-check passed. Hosted gates must follow exact PR head.

Adversarial review retained current contradiction, incomplete read, discovery/
topology generation, newer field preservation, stale receipt, fixed deadline,
equality-negative, external Spa, Safety ceiling and STOP tests. New failed-read
controls prove the idle backstop does not fabricate a fresh BODY clock. STOP
returns the existing snapshot without starting a read or publishing new work.
The new independent-opportunity test asserts no accepted command/lease during
idle, then acquires BODY only through actual accepted delivery. The complete
Pool/Spa simulation retains exact origin, verified domains, coastdown/pump-zero,
independent body generations, no autonomous opportunistic Gas and no duplicate
stable/idle delivery. No source/time/quality/generation gate was relaxed.
