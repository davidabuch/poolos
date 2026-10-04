# PoolOS Current Development Handoff

## Current status — October 2, 2026

PoolOS is in **1.0 release-candidate readiness**.

The production Home Assistant installation is HACS-managed and physically commissioned with
scoped live control. The previous observation-only / global operating-mode commissioning model
is historical and must not be used as current runtime truth.

Current production integration line: `1.0.8`; release candidate: `1.0.10`.

PoolOS 1.0 is released. PR #389 introduced the coherent observation/accepted-command
chronology repair shipped in v1.0.3: truthful per-concept observation timestamps,
immutable authoritative input composition, and shared post-acceptance evidence
admission across orchestration, ownership, thermal execution, cleanup, and filtration.

Phase 4 commissioning of v1.0.3 exposed one fail-closed liveness gap: Waterfall,
Jets, and Slide could remain correctly OFF while their truthful startup observation
timestamps aged past strict freshness. Periodic reconciliation republished cached
native values without genuinely re-reading CIRCUIT STATUS, leaving Thermal blocked
with `thermal_orchestration_shared_hydraulic_inventory_incomplete` despite a
COMPLETE native inventory.

PR #391 fixes that commissioning defect without weakening chronology or freshness.
When shared-hydraulic safety evidence is stale, PoolOS performs one bounded read-only
native safety-topology reobservation for that evidence epoch through the existing
GetParamList path. It does not fabricate timestamps, restore ownership from state,
add a polling loop, or command equipment. v1.0.4 packages that hotfix for continued
physical re-commissioning.

Phase 4 commissioning of v1.0.4 then exposed two additional compatibility/liveness defects. First,
Reset could reach and verify the OFF/0 safe baseline, close Reset authority from its
coordinator-listener fallback after a long-running service timeout/cancellation, yet fail to
publish a subsequent normal authoritative epoch. PR #394 makes Reset closure itself schedule
one fresh coordinator evaluation after the fence closes. Second, PMPCIRC identity resolution
still compared each object timestamp to the whole transport snapshot timestamp, so unrelated
native publications could make a valid Pool/Spa pump assignment disappear. PR #395 removes that
obsolete whole-snapshot equality while preserving the configured target's own field chronology.
v1.0.5 packages both fixes for continued physical re-commissioning.

Phase 4 commissioning of v1.0.5 then proved PMPCIRC identity and physical Pool Solar
delivery but exposed one remaining accepted-step verification gap. PoolOS reached Pool ON,
Solar ON, and 2900 RPM, yet unchanged BODY activity could age beyond the strict 30-second
live freshness window before an accepted pump step finished verification. PR #399 adds one
receipt-bound, bounded read-only native reobservation for every accepted thermal step.
Stale BODY evidence remains fail-closed and cannot verify anything; it waits for genuine
fresh evidence until the original fixed deadline. Fresh contradiction, unusable evidence,
operator intervention, and safety blockers still fail normally. v1.0.6 packages this fix
for continued physical re-commissioning.

Phase 4 commissioning of v1.0.6 then proved the accepted-step reobservation path but
exposed the remaining stable-converged ownership case. A restart returned with Pool ON,
Solar ON, and 2900 RPM already physically converged, so no new accepted command existed
to trigger a one-shot receipt-bound read. The prospectively adopted Pool lease later
preempted on stale `pool.active` evidence even though subsequent native reads confirmed
the same topology. PR #401 extends the existing 15-second bounded read-only native
reobservation loop from probe/priming to any live OWNED thermal lease. It stops when
ownership ends and does not create or restore ownership from matching state. v1.0.7
packages this stable-session evidence liveness fix for continued physical commissioning.

Phase 4 commissioning of v1.0.7 then physically verified Reset reduction to Pool OFF,
Spa OFF, Solar OFF, and pump 0 RPM, but Automatic Thermal remained blocked on
`automatic_thermal_fresh_epoch_required_after_authority_change`. The post-close
coordinator refresh from PR #394 did occur; the failure was identity, not missing
evaluation. Because the safe-baseline native evidence was unchanged across Reset closure,
the orchestration snapshot identity was unchanged and the automatic runtime correctly
deduplicated what appeared to be the same execution epoch. PR #403 makes the chronology
model explicit at this boundary: immutable native evidence retains its evidence identity,
while Reset closure advances a separate authority/evaluation generation that participates
in orchestration evaluation identity. The same safe evidence can therefore be reevaluated
under newly reopened authority without fabricating observations, weakening freshness, or
replaying a cached pre-Reset command candidate. v1.0.8 packages this fix for continued
physical commissioning.

Phase 4 commissioning of v1.0.8 then exercised Reset while Pool, Spa, Solar, and pump
were already at the OFF/0 safe baseline. Reset correctly rejected the pre-Reset native
facts as proof of a new recovery epoch, but its bounded verifier only requested normal
coordinator refreshes. Because unchanged native BODY/source/PUMP state was not genuinely
re-read, the per-concept observation timestamps remained older than the Reset boundary
and Reset eventually failed with `Reset shutdown dispatched but safe baseline was not
verified within the bounded recovery window`. PR #405 adds a dedicated bounded read-only
Reset-baseline reobservation through the existing native PMPCIRC/PUMP/SENSE/BODY path
before each verification publication. The strict safe-baseline predicate is unchanged;
no freshness relaxation, fabricated timestamp, polling loop, ownership-from-state, or
equipment command was added. v1.0.10 packages this already-safe Reset liveness repair.

See [ADR-111](adr/ADR-111-observation-and-command-consequence-chronology.md) for the
chronology model. PR #388 was closed as superseded by PR #389.


## Chronology recovery audit closure — October 3, 2026

After the v1.0.3 chronology substrate change, physical commissioning was paused and the
pre-change physical behavior was treated as a mandatory recovery matrix rather than
continuing one hotfix/deployment at a time.

The repository-wide liveness audit used this adversarial condition for every commissioned
lifecycle:

> Hardware remains unchanged and IntelliCenter emits no unsolicited callback.

The audit distinguishes observation freshness, immutable evidence identity, and
authority/evaluation generation. A genuine native read may advance observation chronology
without changing evidence value or inventing operator intent; Reset/restart may advance
authority generation without changing physical state.

The audit confirmed existing bounded native liveness mechanisms for:

- shared-hydraulic Waterfall/Jets/Slide safety topology;
- every accepted automatic thermal verification step;
- stable OWNED thermal pump/body sessions;
- Spa startup topology;
- thermal source/body cleanup and coastdown verification;
- Reset safe-baseline verification, including already-OFF/0 hardware;
- Reset closure authority/evaluation generation;
- PMPCIRC identity independent of unrelated snapshot publications;
- quick-restart thermal recovery from a positively verified checkpoint.

Two remaining chronology regressions were found in automatic filtration:

1. A verified stable filtration session had no native keepalive. Its BODY/PMPCIRC/pump
   evidence could age beyond the 120-second steady-state window and oscillate
   OWNED -> SUSPENDED -> OWNED while unchanged hardware continued normally. PR #407
   adds a 15-second read-only native reobservation loop only while a verified filtration
   lease owns circulation. The existing fail-closed suspension remains unchanged if
   fresh truth cannot be obtained.
2. Accepted filtration BODY_ON, pump-setpoint, and BODY_OFF steps could wait for an
   unsolicited callback even after a physically successful command. PR #408 adds one
   receipt-bound read-only native refresh per accepted filtration attempt. Verification
   still requires authoritative evidence strictly after command acceptance and retains
   the original fixed deadline.

No freshness threshold was lengthened, no cached value is republished as fresh truth,
no matching physical state creates ownership, and no audit repair adds an equipment
command.

The recovery software matrix now covers the previously commissioned behaviors that were
at risk from chronology/liveness changes: Pool Solar cold start/probe, stable Solar hold,
target-down shutdown, target-up/new-opportunity reacquisition, filtration start/hold/
completion/shutdown, Reset from active and already-safe hardware, verified quick restart,
Spa startup/steady ownership/cleanup, thermal-to-filtration circulation handoff, and
shared-hydraulic safety under unchanged native state.

The broader ownership scenario traceability file still intentionally identifies future
or partially implemented product semantics such as general prospective thermal adoption,
durable ICP/OCP session-override persistence, generalized autonomous recovery after
exhausted command failure, and generalized operator-assisted convergence. Those are not
claimed complete by this chronology recovery audit and must not be silently implemented
as part of the recovery deployment. They require separate architecture/commissioning
work.

**Pre-deployment gate:** PRs #407 and #408 are merged with required CI green. The recovery
release candidate is v1.0.10; it must pass its complete version-aligned release CI before tagging
and physical deployment.
Physical commissioning after deployment must run the whole recovery matrix rather than
only the last observed defect.

## Production control model

PoolOS is the default autonomous controller for its commissioned domains and yields only to
positive intentional operator control or higher-priority safety authority.

Authority is domain-scoped:

- BODY;
- PUMP;
- THERMAL.

Top-level runtime control profiles are descriptive:

- `SCOPED_LIVE`;
- `MANUAL_CONTROL`;
- `OBSERVE_ONLY`.

Production gates currently include:

- Automatic Filtration Execution;
- Automatic Thermal Execution;
- Thermal Live Execution;
- Grid Outage Physical Safety;
- Pool / Hot Tub sanitation;
- PoolOS Maintenance Mode (global physical-command deny).

## Verified 1.0-readiness state

Release `v0.11.104` removed the obsolete persisted `operating_mode=OBSERVE` setting and
replaced the hard-coded global command-delivery-disabled status with canonical runtime truth.

Physical production verification after the v0.11.104 restart showed:

- integration loaded successfully;
- observation health healthy;
- control profile `SCOPED_LIVE`;
- manual command delivery available;
- autonomous command delivery enabled;
- automatic filtration enabled;
- automatic thermal enabled;
- Thermal Live enabled;
- Grid Outage Physical Safety enabled;
- Maintenance Mode OFF.

The config-entry migration removed the legacy `operating_mode` field from live config data.

## Core behavioral contracts

Use these as normative sources rather than reconstructing behavior from historical handoff text:

- `docs/ownership/PoolOS_Ownership_Scenario_Contract.txt`
- `docs/ownership/OWNERSHIP_ARCHITECTURE_SPEC.md`
- `docs/PUMP_SPEED_SESSION_CONTROL_SPEC.md`
- sanitation ownership/scenario contract under `docs/ownership/`
- current ADRs for physical command authority, thermal execution, outage safety, and native transport.

Historical ADRs and release forensic records remain valuable evidence of why the current
architecture exists, but their milestone-era authority boundaries are not current product state.

## Current priorities

1. Complete 1.0 metadata/version alignment.
2. Finish universal pump capability abstraction so GPM controls are enabled only from positive
   adapter capability evidence and trustworthy native limits.
3. Continue minor edge-case hardening without weakening proven ownership, currentness,
   verification, shutdown, or restart behavior.
4. Physically commission any new or expanded authority before calling it complete.

## Engineering workflow

Continue autonomously through:

```text
inspect
-> diagnose
-> reproduce
-> implement
-> regression test
-> validate
-> push / PR
-> monitor CI and fix until green
-> merge
-> release
-> deploy
-> verify Home Assistant runtime
-> physically commission
-> document
```

Stop only at a genuine human/physical/Terminal/safety/design/permission boundary.

Repository truth is code/CI truth. Home Assistant is deployed-runtime truth. Physical equipment
behavior is final commissioning truth.

## Current 1.0 caveat

Do not equate "minor remaining edge cases" with permission to weaken fail-closed behavior.
Unknown capability, stale evidence, unexplained state, failed verification, or ambiguous
provenance must remain bounded according to the applicable domain contract.

## v1.0.22 native arbitration evidence candidate (2026-10-03)

Baseline `ffd8617fa77c484d3f944c97c494dba94269a7f1`; candidate branch
`fix/native-arbitration-evidence-contract`. See
`docs/NATIVE_ARBITRATION_EVIDENCE_AUDIT.md` for the historical audit, complete
concept/source/currentness matrix, lifecycle read scheduling, red regressions,
restart findings, and physical acceptance sequence.

The candidate consolidates existing lifecycle rereads into one complete,
serialized, request-start-dated native arbitration contract. It preserves strict
receipt/entitlement chronology, domain provenance and fail-closed partial reads.
Fresh-policy Spa restart restoration is command-free and limited to the existing
reviewed fully verified checkpoint scope; invalid restoration discards its origin
preview. Configured RPM and shared topology now gate restoration explicitly.

Software modeling covers Pool Solar target-down/source-Off/body-Off/pump-zero,
deferred idle, target-up/new Pool acquisition, and a fully fresh Spa restart with
independent Pool priority return. The ten-minute target-satisfaction debounce is
unchanged. Full unchanged cleanup batches already passed on v1.0.22; do not claim
an undocumented live failure or physical confirmation from these tests.

This task stops at reviewed PR/green validation. No merge, release, deployment or
equipment action is authorized by this candidate note. Real native reply timing,
completeness and the complete physical target-down/target-up cycle still require
operator commissioning after eventual review/release.

## HA STOP lifecycle repair (v1.0.23 follow-up)

The v1.0.23 commissioning passed manual Pool/Spa attribution, currentness and
restart fail-closed checks, but exposed a thermal reobservation loop surviving
HA final writes. The integration STOP listener previously quiesced only the
coordinator. STOP and config-entry unload now share command-free entry teardown:
synchronously fence all producers, cancel/await owned background work, settle
already-dispatched results and disconnect transports. Only an already-valid
quick-restart checkpoint is frozen for final writes, with unchanged provenance
and age. Arbitration and ownership policy are unchanged.

See [HA_STOP_TASK_QUIESCENCE_AUDIT.md](HA_STOP_TASK_QUIESCENCE_AUDIT.md) for the
red regression, task inventory, ordering and remaining physical validation.

## Systemic arbitration currentness recovery (v1.0.24 follow-up)

Baseline `dc67ad4b8fdf769287a5b83e7b4bfda965ad5953`. Compatible native callbacks
could invalidate every complete arbitration read, leaving unchanged BODY/source/
shared-circuit clocks stale while RPM telemetry and observation health remained
good. The shared read now fences discovery/topology identity and contradictory
critical fields, preserves newer measurements, and dates only genuinely returned
fields at conservative read start. An immutable read record adds diagnostics;
it grants no ownership, intent, command or cleanup authority.

Pending filtration acquisition retains its accepted attempt during transient
evidence loss and retries the same shared read until its original deadline.
Timeout remains a control fault; operator and topology gates remain authoritative.
PR #442 shutdown quiescence and the operator's disabled Thermal gate are unchanged.

See [SYSTEMIC_ARBITRATION_CURRENTNESS_AUDIT.md](SYSTEMIC_ARBITRATION_CURRENTNESS_AUDIT.md)
for history, red regressions, all 36 lifecycle boundaries, physical evidence
limits and commissioning sequence. The maintainable A–BJ prediction matrix is
`docs/ownership/systemic_currentness_prediction_matrix.json`; it does not claim
all 90 ownership scenarios or physical commissioning. No live operation,
deployment, release or merge occurs in this recovery task.
