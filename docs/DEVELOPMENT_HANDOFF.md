# PoolOS Current Development Handoff

## Purpose

This document is the current working handoff for PoolOS development.

It is intentionally different from `AGENTS.md`.

- `AGENTS.md` is the durable repository safety and architecture constitution and has higher precedence.
- This document records current project state, recently completed work, commissioning status, active design decisions, and the next development milestone.
- `docs/PUMP_SPEED_SESSION_CONTROL_SPEC.md` contains the currently approved pump-speed/session behavioral contract.

Repository truth and current authoritative runtime evidence always outrank this handoff if they disagree.

---

## Current Repository State

### September 12, 2026 — v0.11.15 release preparation

Release candidate `v0.11.15` contains the residual cleanup transfer correction
merged by PR #179 on top of `v0.11.14`.

The release changes integration/package metadata only; no additional runtime
behavior is introduced beyond the already-reviewed PR #179 fix.

### September 12, 2026 — residual cleanup transfer correction

The verified baseline for this correction is `v0.11.14`, commit `e835c85`.
The September 9 release/slice status below is historical.

A deterministic lifecycle regression reproduced loss of verified Pool body/pump
provenance after probe supersession: a fresh source-Off observation predating
the residual boundary prevented cleanup capture, but termination consumed the
residual anyway. Later Solar then established pump/source ownership without the
original body origin. Source ages of 1, 29, and 119 seconds reproduced the loss;
this was not a freshness-window failure.

Both termination capture callers now require an explicit capture disposition.
When circulation proof cannot yet transfer, the exact residual remains in
`CLEANUP_WAITING`, without command authority. Each new authoritative epoch
rechecks the existing termination and arbitration evidence. A sufficiently
current source-Off observation permits capture; only then is the residual
consumed. Source-only residuals, and Hot Tub residuals without the body origin
required by the existing Hot Tub cleanup scope, have no supported circulation
capability to transfer and retain their existing terminal disposal behavior.

Waiting does not renew a lease, change `retained_at`, extend freshness, or reset
verification deadlines. It retains one in-memory token. Missing/stale evidence
remains a command-free block under existing policy; positive takeover/topology
invalidation, a new accepted ownership generation, and unload/restart discard
old authority. No new wall-clock disposal timeout is introduced. Successful
source-Off verification ends its attempt even if cleanup capture must wait, so
the verified command is not replayed merely to retry capture.

The regression follows cleanup-first policy when Solar becomes eligible during
the wait: verified Pool OFF/pump 0, a fresh accepted Pool activation for Solar,
and target-satisfied source Off followed by either verified body Off/pump 0 or
the existing 2600-RPM immediate-filtration handoff. The probe-successor predicate
and opportunistic Hot Tub policy are unchanged. Tests do not establish physical
commissioning or conclusively attribute the recorded run without its raw trace.

As of September 9, 2026:

- Current released integration: `v0.11.7`
- `v0.11.7` includes the live thermal ownership/cleanup repair from PR #158 and the release-contract work from PR #159.
- Current `main` is newer than the `v0.11.7` release.
- PR #160 added body-specific Hot Tub RPM manual control to `main`.
- Therefore the Hot Tub RPM entity is currently on repository `main` but is not part of the already-created `v0.11.7` release tag unless a later release has since been created.

Always verify current `origin/main`, tags, and releases before assuming this section is still current.

---

## Development Workflow

PoolOS development follows this sequence:

1. inspect current repository and tests;
2. define/reproduce the exact behavior or defect;
3. create a bounded feature/fix branch from current `origin/main`;
4. implement the smallest coherent change;
5. run focused tests;
6. run participating/expanded suites;
7. run full pytest;
8. run Ruff;
9. run MyPy;
10. run compileall;
11. run `git diff --check`;
12. review actual production diff;
13. stage only reviewed files;
14. commit and push;
15. open PR;
16. require green CI;
17. merge;
18. create a release branch only when preparing a release;
19. update the integration version/release contract;
20. merge the release PR;
21. create and push the matching annotated tag;
22. update through HACS/normal release path;
23. restart Home Assistant when required;
24. perform live commissioning with read-only observation first.

Do not deploy arbitrary unmerged working-tree source as the normal workflow.

Do not inspect or modify `.local_backups/`.

Do not stage, commit, push, merge, tag, release, package, or deploy unless the current task explicitly reaches that step.

---

## Current PoolOS Architecture

PoolOS now uses native IntelliCenter observation and command paths rather than the retired legacy Home Assistant IntelliCenter integration for primary pool equipment truth.

Important concepts remain distinct:

- native observed equipment state;
- configured state;
- policy recommendation;
- execution plan;
- command authorization;
- submitted command;
- accepted delivery receipt;
- later authoritative observation;
- verification;
- execution provenance;
- runtime ownership;
- cleanup authority.

A matching physical state never proves PoolOS caused it.

Accepted command delivery is not physical verification.

Body activation ownership, pump-setpoint provenance, and heat-source provenance are concept-specific.

Restart does not reconstruct ownership from matching hardware state.

---

## IntelliCenter Pump Model

Pool and Hot Tub use body-specific PMPCIRC assignments discovered dynamically from native IntelliCenter inventory.

Do not hard-code `p0101`, `p0102`, or equivalent identities.

Current `main` provides:

- a Pool RPM manual number entity;
- a Hot Tub RPM manual number entity;
- dynamic Pool PMPCIRC resolution;
- dynamic Spa/Hot Tub PMPCIRC resolution;
- native pump limits;
- exact body binding for manual commands.

The configured PMPCIRC speed and actual physical pump RPM remain separate observations.

The Hot Tub RPM entity was added in PR #160.

---

## Filtration

Current filtration policy remains obligation-based.

Temperature bands currently used by the project are:

- <=70 F: 6 hours
- <=80 F: 8 hours
- <=85 F: 9 hours
- <=90 F: 10 hours
- >90 F: 12 hours

Filtration tracks:

- required runtime;
- credited runtime;
- remaining debt;
- current disposition;
- immediate requirement;
- TOU/catch-up behavior.

A scheduled interval does not itself earn credit.

Spa-only circulation does not automatically count as Pool filtration.

Remaining filtration debt may be deferred to the configured preferred catch-up period when policy allows.

Do not change filtration debt/TOU semantics incidentally while working on pump-speed configuration.

---

## Thermal Commissioning

Pool thermal execution has progressed from observation through live commissioned execution.

Important safety gates remain explicit.

Live thermal execution and automatic thermal execution must continue to preserve:

- currentness;
- exact PMPCIRC identity;
- source verification;
- body topology;
- manual intervention preemption;
- ownership/provenance boundaries;
- accepted-versus-verified distinction.

Solar uses IntelliCenter source `H0002`.

Gas uses IntelliCenter source `H0001`.

No heat uses `00000`.

Selected source and actual active heating are not the same concept.

---

## PR #158 - Live Thermal Ownership / Cleanup Repair

PR #158 repaired a major no-restart runtime ownership and cleanup lifecycle.

The repair established, among other things:

- accepted commands may remain pending while IntelliCenter state converges;
- an old native consequence immediately after accepted delivery is not necessarily external takeover;
- exact post-acceptance observations are required for command verification;
- accepted-but-unverified provenance is not cleanup proof;
- body, pump, and source provenance remain concept-specific;
- configured PMPCIRC and actual RPM verification may arrive in either order;
- manual/external intervention still preempts;
- stale or contradictory hydraulic evidence fails closed;
- body cleanup requires valid verified body-origin provenance;
- cleanup OFF acceptance is not completion;
- later authoritative body OFF observation verifies cleanup;
- duplicate cleanup OFF commands are prevented;
- restart intentionally reconstructs no ownership/cleanup authority.

Do not undo these semantics while implementing pump-speed work.

---

## Known Live Behavior Exposing the Next Pump Architecture Gap

A live v0.11.7 test exposed an important remaining problem.

Test conditions:

- roof cold;
- Solar inactive;
- filtration already satisfied;
- user manually turned Pool ON;
- IntelliCenter started/retained the Pool PMPCIRC at approximately 2900 RPM;
- no heat source was active;
- PoolOS classified the body as externally/pre-existing active and automatic thermal execution was blocked by `automatic_thermal_preexisting_body_unowned`.

Result:

Pool remained at approximately 2900 RPM instead of the intended ordinary/no-heat RPM of 2600.

This is NOT fundamentally a BODY_ACTIVATION ownership problem.

Approved architecture now states:

> Pump-speed governance is separate from body-activation ownership.

PoolOS may govern the exact PMPCIRC of an externally activated body without thereby gaining authority to turn that body OFF.

This behavior is intentionally NOT being fixed in Slice 1.

It belongs to a later pump-governance slice after canonical configurable baseline plumbing is complete.

---

## Approved Pump-Speed Architecture

The accepted detailed contract lives in:

`docs/PUMP_SPEED_SESSION_CONTROL_SPEC.md`

Key principles:

1. Pump RPM is primarily a function of current operating purpose and applicable safety/feature floors, not body-activation ownership.
2. RPM baselines are user-configurable.
3. Configured baselines establish session defaults.
4. Explicit user RPM changes override the default for the remainder of that pump session.
5. True operating-purpose/body transitions end the prior RPM override.
6. High Speed is a distinct user-selected minimum floor.
7. Direct manual RPM adjustment cancels High Speed.
8. Body OFF and Pool/Hot Tub transitions cancel High Speed.
9. Grid outage is ultimately intended to perform a one-time protective intervention, after which deliberate user control is again respected.
10. PoolOS may govern RPM on externally active bodies without body shutdown authority.
11. PoolOS may later adopt an externally started body when PoolOS independently develops a valid reason that would have caused it to activate that body.
12. Solar completion must respect TOU filtration deferral and opportunistic Hot Tub heating rather than automatically running ordinary filtration all afternoon.

Do not implement all of these concepts at once.

---

## Pump-Speed Implementation Slices

The approved implementation sequence is deliberately incremental.

### Slice 1 - Canonical Configurable Pump Baselines

NEXT TASK.

Replace independently instantiated hard-coded pump RPM baselines with one canonical runtime-configured `PumpOperatingBaselines` policy derived from Home Assistant config/options.

Required configurable values:

- ordinary / filtration RPM;
- Solar heating RPM;
- Gas heating RPM;
- temperature probe RPM;
- priming RPM;
- grid outage RPM.

Preserve existing spillway RPM semantics.

Do not add High Speed yet.

Do not alter session semantics yet.

Do not alter ownership semantics yet.

Critical success criterion:

> A configured RPM must be consistently used by policy, planning, immutable dispatch/context construction, final physical authority, and delivery.

A UI value that only changes some layers is a failed implementation.

### Slice 2 - Pump Session / Manual RPM Override Model

Introduce explicit pump-session identity and session-scoped direct manual RPM overrides.

Do not conflate this with body activation ownership.

### Slice 3 - Ownership-Independent Active-Body RPM Governance

Allow PoolOS to establish appropriate RPM for an already-active Pool or Hot Tub even when PoolOS did not cause body activation.

This slice addresses the live cold-roof/manual-Pool-ON 2900-RPM problem.

Changing RPM must not grant body shutdown authority.

### Slice 4 - High Speed

Implement configurable High Speed floor and approved cancellation/transition rules.

### Slice 5 - Body Adoption

Allow PoolOS to adopt an already-active externally started body when PoolOS independently reaches a policy state where it would itself activate that body.

Adoption must be explicit and evidence-backed.

### Slice 6 - TOU / Solar Completion / Opportunistic Hot Tub Handoff

Verify and, where required, implement the approved relationship between:

- Pool Solar completion;
- remaining filtration debt;
- TOU deferral;
- ordinary circulation;
- opportunistic Hot Tub Solar heating.

### Slice 7 - Grid Outage Behavior Revision

Separately redesign outage behavior to the approved one-time protective intervention model.

Do not smuggle this redesign into earlier slices.

---

## Slice 1 Warning: Current Multiple-Baseline Problem

Current production code contains many independent `PumpOperatingBaselines()` constructions and import-time baseline values.

Known consumers include:

- filtration policy;
- thermal source policy;
- thermal operating-purpose policy;
- Spa thermal policy;
- pump priming policy;
- thermal runtime assessment;
- thermal runtime orchestration;
- thermal live execution;
- thermal automatic execution;
- physical command authority;
- grid outage physical safety;
- filtration delivery;
- thermal delivery.

Some immutable dispatch/context classes also validate requested RPMs against module-global default baselines during `__post_init__`.

Therefore Slice 1 must not merely add Home Assistant settings.

It must eliminate live-runtime split-brain behavior where one layer uses configured values and another silently retains defaults.

---

## Home Assistant Options

The current options flow already contains configuration for items such as:

- observation/entity mappings;
- diagnostics;
- preferred filtration catch-up start;
- IntelliCenter host/transport.

Pump RPM baseline options are not yet present as of this handoff.

Slice 1 should add an explicit Pump Speeds options surface and construct one immutable effective policy per loaded config entry.

---

## Restart / Reload

Restart remains intentionally fail-closed for ownership.

Do not reconstruct:

- body ownership;
- pump ownership;
- source ownership;
- cleanup authority;
- manual RPM override intent

merely from matching physical state after restart.

Future pump-session work may define bounded post-restart reconciliation, but it must not manufacture provenance.

---

## Manual OFF Suppression

Current manual body-OFF behavior remains safety-sensitive.

A manual Pool or Hot Tub OFF preempts autonomous work for that body.

Approved future behavior additionally states:

- explicit manual ON of that same body clears its Resume-required suppression;
- the new activation remains externally originated;
- PoolOS may later adopt it only after independently developing valid activation purpose.

Do not implement this incidentally in Slice 1.

---

## Current Development Priority

Immediate next development task:

**Slice 1 - Canonical Configurable Pump Baselines**

The Slice 1 implementation prompt should require:

- repository-wide baseline audit;
- failing-before tests with non-default RPMs;
- one canonical HA-derived immutable policy;
- propagation through nested runtime dependencies;
- removal of operational reliance on import-time defaults;
- exact-purpose final authority;
- policy binding/fingerprint to prevent stale-policy work after reload;
- Pool and Hot Tub coverage;
- filtration, Solar, Gas, probe, priming, and outage coverage;
- full validation;
- no authority expansion;
- no deployment.

After Slice 1 is reviewed and merged, proceed to Slice 2.

---

## Handoff Rules for Coding Agents

Before editing:

1. read `AGENTS.md`;
2. read this file;
3. read `docs/PUMP_SPEED_SESSION_CONTROL_SPEC.md` for pump work;
4. inspect current `origin/main`;
5. inspect relevant current tests and production files;
6. trust repository/runtime evidence over this handoff if newer evidence differs.

Do not stop merely because a safe bounded refactor is required.

Do stop if the requested behavior would require weakening a safety invariant or if repository evidence makes the requested design logically unsafe.
