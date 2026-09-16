# Stage 2 ownership lifecycle reconciliation

## Scope

Stage 2 implements the first production subset of ADR-110 on branch
`feat/ownership-lifecycle-reconciliation`, based on main
`629b84e7517669e9dd5b98285ec1357a0b9086f4`. It does not claim complete
implementation of the 90-scenario contract and does not establish physical
commissioning.

The implemented slice provides:

- one typed evidence vocabulary for expected native transition, unexplained
  drift, positive operator intervention, safety change, old-generation
  consequence, command/control failure, and legitimate lifecycle transition;
- separate BODY, PUMP, and THERMAL authority and health on the existing thermal
  lease and filtration circulation lease;
- fixed reconciliation episodes bound to authority generation, body session,
  domain, equipment, policy, origin and target, with a 120-second absolute
  deadline and two reserved correction identities;
- exact positive-operator evidence created by PoolOS's direct manual command
  adapter and bound to the current domain generation and body session;
- continuous Pool BODY identity through typed Filtration-to-Thermal and
  Thermal-to-Filtration transfers;
- Solar preparation at ordinary circulation RPM, distinct from the 2900-RPM
  operating requirement after `solar.active` becomes true;
- retained BODY completion responsibility through PUMP or THERMAL drift and
  command failure;
- successful shutdown only after Pool Off and actual pump RPM zero;
- cancellation of the current manual-Off semantic opportunity without blocking
  a later independent filtration or thermal opportunity; and
- expanded canonical runtime diagnostics for domain authority, origin,
  evidence, reconciliation, permission, body session, execution purpose and
  opportunity cancellation.

## Evidence and authority behavior

An unmatched native value is unattributed. It may start or advance bounded
reconciliation, but it cannot create External/operator authority. A matching
value cannot create PoolOS authority or verify the wrong accepted operation.
Only a positively recorded operator request with the exact current generation,
body session, domain, equipment and chronology yields that domain. Current
IntelliCenter snapshots do not expose a defensible ICP/OCP actor identity, so
native callbacks never create this record.

PUMP or THERMAL degradation retains BODY completion responsibility. The exact
domain may deny ordinary commands while evidence is stale or unusable. A
separately authorized safe completion reduction still passes through existing
topology, currentness, ownership, circulation and physical-command gates.
Positive BODY intervention and incompatible hydraulic topology continue to end
the affected physical body session.

Duplicate evaluation, plan churn, repeated telemetry and reconnect cannot renew
a reconciliation deadline or correction budget. A late match after a fault does
not reopen the episode. Old-generation evidence cannot verify or transfer a new
generation.

## Continuous normal Pool day

The deterministic lifecycle regression covers:

1. OFF with an immediate filtration obligation;
2. accepted and verified Pool activation and 2600-RPM filtration;
3. typed transfer of the same BODY origin into Solar preparation;
4. verified H0002 selection while preparation remains at 2600 RPM;
5. physical Solar engagement and a fresh accepted 2900-RPM operation;
6. source termination and typed return to filtration when immediately required;
7. filtration completion, Pool Off and observed pump RPM zero;
8. retirement of cleanup and circulation authority; and
9. a later independent filtration opportunity acquiring a fresh generation.

Separate regressions cover no-successor Solar completion, native Solar Active
loss plus RPM drift, startup settling, residual-cleanup transfer, rejected Pump
delivery, nonzero RPM after body Off, and positive versus unattributed PUMP and
THERMAL contradictions.

## Compatibility and deliberate limits

The existing v0.11.23 armed-H0002 neutralization remains: source Off is verified
before cold-start circulation and later deliberate Solar selection. Strict
post-acceptance verification, no equality adoption, immutable execution
currentness, generation isolation, dynamic PMPCIRC identity, hydraulic safety,
and the single final command gateway remain in force.

This slice does not implement Reset PoolOS Control, general restart adoption,
durable manual-override persistence, operator-assisted recovery from an already
faulted convergence episode, broad Hot Tub prospective adoption, or a new native
ICP/OCP intent source. Those scenarios remain partial or unimplemented in the
traceability matrix. The correction budget is exercised for filtration drift;
thermal reconciliation remains conservative where no existing safe correction
operation is currently authorized.

## Principal regressions

- `tests/test_ownership_evidence.py`
- `tests/test_ownership_lifecycle_reconciliation.py`
- `tests/test_ownership_opportunity_cancellation.py`
- `tests/test_probe_successor_real_cadence.py`
- `tests/test_residual_cleanup_transfer.py`
- `tests/test_systemic_autonomy_closure_guard.py`
- the participating thermal ownership, automatic execution, termination,
  circulation successor, filtration execution, pump-session and HA runtime suites

The systemic guard now distinguishes unattributed contradiction from positive
operator evidence. It still freezes accepted-command chronology, generation
isolation, restart behavior, no equality adoption, liveness bounds and the full
production reason-family inventory.
