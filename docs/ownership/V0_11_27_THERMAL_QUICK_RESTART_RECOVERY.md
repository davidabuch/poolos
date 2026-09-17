# v0.11.27 Thermal quick-restart recovery

## Purpose

This record documents the narrowly bounded thermal ownership recovery added
after physical v0.11.27 commissioning exposed an operational restart gap.

Before this correction, a routine Home Assistant restart discarded volatile
PoolOS BODY/PUMP/THERMAL ownership even when the IntelliCenter equipment never
changed physically. A PoolOS-owned Pool Solar session could remain physically
Pool ON, Solar selected/active and pump 2900 RPM, yet PoolOS returned unowned
after restart and correctly refused destructive cleanup of the pre-existing
body.

That behavior was provenance-safe but operationally unsuitable for routine
Home Assistant maintenance.

## Scope

This correction addresses only the short, unchanged-restart case.

Recovery is eligible only when all of the following are true before restart:

- body is Pool;
- BODY, PUMP and THERMAL are all PoolOS authority;
- all three domains are stable;
- BODY activation, pump setpoint and heat-source provenance each originate from
  accepted PoolOS deliveries;
- all three accepted consequences have been authoritatively verified;
- the semantic purpose is active Pool thermal control using Solar;
- the required operating pump target matches the owned pump provenance;
- there is no positive operator evidence in any recovered domain.

The checkpoint age limit is five minutes.

This is not physical-equality adoption.

## Durable checkpoint

The Automatic Thermal Execution RestoreEntity persists a JSON-safe checkpoint
containing the exact previously earned ownership provenance and body-session
identity.

The checkpoint preserves:

- ownership lease identity and generation;
- body-session identity and generation;
- semantic purpose identity;
- accepted BODY/PUMP/THERMAL command provenance;
- accepted-at chronology boundaries;
- previously verified ownership concepts.

A checkpoint is exported only from a fully stable, fully verified Pool Solar
session.

Repeated Home Assistant state writes do not refresh checkpoint age. The
checkpoint timestamp is the lease's last authoritative confirmation time.

## Startup adjudication

On Home Assistant startup, restoring the desired Automatic Thermal Execution
switch may arm one checkpoint candidate.

Armed does not mean owned.

Startup authority restoration is part of the recovery boundary.  A checkpoint
remains armed while Maintenance/controller authority is still unresolved during
Home Assistant initialization.  Those transient startup frames are not recovery
attempts and issue no equipment work.  Once startup authority resolves, the first
fresh authoritative thermal epoch adjudicates the checkpoint before ordinary
automatic command scheduling.

Recovery requires:

- checkpoint age within five minutes;
- fresh post-checkpoint authoritative observations;
- Pool active;
- Spa inactive;
- pump RPM matching the prior owned operating setpoint within the existing
  ownership tolerance;
- heat source still matching the prior owned Solar selection;
- the fresh semantic purpose ID matching the persisted purpose;
- compatible requested mode, body, source and operating pump requirement;
- no external-change events.

Any mismatch denies recovery.

A denied checkpoint is consumed once and cannot later gain authority merely
because physical equality persists.

## Successful recovery

Successful recovery:

- preserves the exact prior lease identity and generation;
- preserves accepted BODY/PUMP/THERMAL provenance;
- preserves body-session identity and generation;
- advances only transient evaluation/plan identity to the fresh compatible
  post-restart currentness context;
- restores thermal circulation ownership in lockstep with the thermal lease;
- records the fresh physical-authority epoch;
- issues no equipment command on the restoration epoch.

The explicit reason is:

`runtime_ownership_restored:quick_restart`

The diagnostic distinction is intentional:

- `quick_restart_recovery_armed=true` means a persisted candidate is awaiting
  adjudication;
- `physical_session_ownership_restored=true` means restoration actually
  succeeded.

## Fail-closed boundaries

Quick restart recovery is denied for:

- stale checkpoint;
- clock regression;
- changed semantic purpose;
- missing currentness;
- external-change evidence;
- Pool not active;
- Spa active or unusable;
- pump mismatch or unusable pump evidence;
- heat-source mismatch or unusable source evidence;
- unsupported body;
- partial or unverified prior ownership;
- non-stable ownership;
- operator-scoped authority.

Malformed or unknown checkpoint schemas are discarded.

Recovery never manufactures authority from physical equality.

## Explicitly out of scope

This correction does not solve long-outage reconciliation.

Example intentionally remaining open:

- 15:00: PoolOS owns Pool Solar at 2900 RPM;
- Home Assistant is offline for hours;
- environmental conditions change while HA is unavailable;
- HA returns after Solar is no longer appropriate.

That case requires a separate durable responsibility/reconciliation design that
evaluates current policy and may need to terminate or hand off the old physical
session. A stale checkpoint from this feature is denied rather than used to
resume old authority.

Also out of scope:

- restart during thermal cleanup;
- restart during partial acquisition;
- Hot Tub restart adoption;
- mixed operator THERMAL authority;
- broad restart adoption based on matching telemetry.

## Regression coverage

Core recovery:

- `test_fully_verified_solar_session_exports_restart_checkpoint`
- `test_matching_fresh_restart_restores_same_provenance_without_new_delivery`
- `test_stale_restart_checkpoint_fails_closed`
- `test_changed_semantic_purpose_fails_closed`
- `test_restart_hardware_mismatch_fails_closed`
- `test_partial_or_unverified_session_cannot_create_restart_checkpoint`
- checkpoint serialization round-trip and schema rejection

Home Assistant runtime:

- `test_quick_restart_success_restores_circulation_and_is_command_free`
- `test_quick_restart_denial_is_consumed_once_and_never_retries_equality`

The systemic reason-family guard includes both the successful restoration reason
and the restart-denial reason family.

## Validation

Pre-commit candidate validation:

- full pytest: 3404 passed;
- Ruff: passed;
- MyPy: passed across 215 source files;
- compileall: passed;
- scenario traceability JSON: valid;
- `git diff --check`: passed.

Physical commissioning is still required after release.

## Physical commissioning gate

The acceptance test is:

1. Establish autonomous Pool Solar operation at 2900 RPM.
2. Verify BODY/PUMP/THERMAL are all stable PoolOS authority.
3. Verify a quick-restart checkpoint is available.
4. Restart Home Assistant without manually changing pool equipment.
5. Confirm Pool remains physically ON, Solar remains selected/active and pump
   remains 2900 RPM.
6. Confirm the restored checkpoint is adjudicated from fresh native evidence.
7. Confirm BODY/PUMP/THERMAL return as PoolOS authority under
   `runtime_ownership_restored:quick_restart`.
8. Confirm thermal circulation ownership references the restored lease.
9. Confirm no corrective Pool, pump or source command is issued merely to
   restore ownership.
10. Allow the recovered session to continue and later terminate normally.

Only after this physical gate passes should short-restart survivability be
considered commissioned.
