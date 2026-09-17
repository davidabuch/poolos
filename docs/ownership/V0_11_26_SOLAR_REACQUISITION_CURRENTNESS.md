# v0.11.26 Solar reacquisition currentness correction

## Scope

This record describes the repository correction developed from main
`c8539e32a6519a35ab2ec2b069698b923e4a3f74` after physical v0.11.26 commissioning.
The already commissioned Solar shutdown path remains unchanged: source Off, Pool
Off, observed pump zero, and complete ownership retirement when no immediate
successor exists.

## Running execution currentness

`maximum_plan_age` remains an admission and continuation safety bound. A thermal
execution with no PoolOS-attributed progress still uses its immutable originating
plan timestamp and cannot begin after that plan ages. A running execution may use
the timestamp of a fresh planner epoch only after accepted or verified progress
exists and `assess_execution_compatibility()` proves that the current semantic
purpose and residual plan are explained by that progress.

The original evaluation, plan and operation sequence remain the audit identity;
they are not rewritten as fresh. A compatible currentness decision does not grant
delivery authority. Current observation freshness, topology, commissioning scope,
domain command permission, positive operator evidence, generation checks,
post-command verification and the final delivery gateway still apply. The fresh
epoch is itself rejected when stale or future-dated. Purpose changes, blocked or
incompatible residuals, and zero-progress look-alikes remain fail closed.

This permits a legitimate BODY/probe/preparation sequence whose authoritative
native cadence exceeds two minutes to deliver its remaining exact Solar source
operation under fresh compatible authority. It does not permit an old plan to
start or an obsolete command to cross a purpose boundary.

## Circulation arbitration

A verified filtration lease can transfer to thermal only through the existing
generation-bound typed handoff. If filtration is acquiring, suspended, or already
in a pending transfer and no current handoff token can be created, thermal returns
`automatic_thermal_circulation_handoff_unavailable` without delivery. It does not
call `mark_thermal_owned()` and cannot replace the legitimate circulation owner.

`FILTRATION_SUSPENDED` remains intentional. Temporarily unusable `pool.active`
evidence denies commands but retains the exact verified lease, BODY/PUMP origin and
cleanup responsibility. Fresh usable evidence resumes that lease. The state is not
an ownership loss and its fixed provenance is not renewed by repeated epochs.

## Mixed manual THERMAL and PoolOS PUMP

Solar operating RPM follows physical Solar Active state. When filtration owns the
continuous BODY/PUMP session at 2600 and Solar becomes active, a typed transfer may
establish the 2900 PUMP requirement even when a trusted operator request owns only
THERMAL. The transfer preserves BODY, obtains PUMP provenance from the accepted
2900 operation, and records the exact generation-bound THERMAL operator token.

Current native IntelliCenter telemetry does not itself prove operator origin.
Identical H0002/Solar Active telemetry without a trusted token establishes no
THERMAL owner. Physical equality never creates provenance.

The reverse transition remains domain-scoped. A later trusted operator source-Off
request keeps THERMAL with the operator; it does not transfer THERMAL back to
PoolOS. Existing PoolOS BODY/PUMP responsibility may hand circulation to an
immediately required filtration successor at 2600, or may complete Pool/pump
shutdown when no successor exists.

## Restart and prospective PUMP provenance

Restart reconstructs no volatile thermal authority. When fresh observations show
Pool active, H0002 selected, Solar active and pump 2600, the current Solar
operating requirement may prospectively issue an explicit 2900 command. Its
accepted receipt and strictly later authoritative 2900 observation establish
PUMP-only provenance. BODY and THERMAL remain unowned unless independently
proven. Repeated epochs while the command is pending do not replay it.

When the same restart instead observes pump already at 2900, no command is
needed and no PUMP provenance exists. Repeated equality remains command-free and
unowned. The implementation does not broadly adopt a pre-restart thermal or
cleanup session. A restart during cleanup therefore discards volatile cleanup
authority and will not replay its old command; safe autonomous closure across
that boundary remains limited to a newly justified prospective mechanism.

## Command chronology and generation isolation

Every thermal BODY, PUMP and source operation requires authoritative consequence
evidence strictly later than its delivery receipt. An older matching observation
cannot verify a new execution even when the semantic purpose is identical. During
a priming hold, each verification sample must advance beyond the preceding
verification epoch; the immutable receipt and execution generation remain
unchanged.

Fresh semantic currentness may admit only the next exact operation after accepted
or verified progress. It cannot replay an accepted operation, transfer a delayed
consequence into another generation, or treat the same purpose as the same
provenance generation.

## Principal regressions

- `tests/test_solar_reacquisition_currentness.py`
- `tests/test_thermal_execution_currentness.py`
- `tests/test_thermal_live_execution.py`
- `tests/test_ownership_lifecycle_reconciliation.py`
- `tests/test_systemic_autonomy_closure_guard.py`
