# PoolOS Commissioning Safety Checklist

Use this checklist before enabling or expanding any physical-control capability.

## Universal requirements

- [ ] Exact capability/domain being commissioned is named.
- [ ] Current physical baseline is captured.
- [ ] Intended operator approval is explicit.
- [ ] Relevant observations are mapped to the correct equipment.
- [ ] Required evidence is current, available, and unit-correct.
- [ ] Unknown, stale, contradictory, or incomplete evidence fails closed.
- [ ] Ownership/preemption rules are documented.
- [ ] Exact command eligibility is bounded.
- [ ] Accepted delivery requires later authoritative verification.
- [ ] Failure/timeout/mismatch behavior is bounded.
- [ ] Termination and hand-back are defined.
- [ ] Restart behavior is covered.
- [ ] Maintenance Mode provides a known global physical-command deny.
- [ ] Manual/native recovery remains available.
- [ ] Regression tests and CI are green.

## Before enabling automatic filtration

- [ ] Filtration obligation/debt is correct.
- [ ] Scheduling mode and catch-up boundary are correct.
- [ ] Thermal/sanitation/outage interactions are covered.
- [ ] Pump target and session identity are correct.
- [ ] Manual body OFF cancellation and later legitimate reacquisition are tested.

## Before enabling automatic thermal

- [ ] Automatic Thermal Execution and Thermal Live Execution semantics are understood separately.
- [ ] Pool and Hot Tub ownership behavior is tested independently.
- [ ] Solar/Gas source selection and source-Off cleanup are verified.
- [ ] Probe, priming, heating, maintenance, termination, and pump-zero behavior are covered.
- [ ] Positive operator heat/source changes preempt correctly.
- [ ] Opportunistic Hot Tub behavior is physically commissioned before production reliance.

## Before enabling Grid Outage Physical Safety

- [ ] Authoritative grid evidence source is correct.
- [ ] Confirmation timing is correct.
- [ ] Reduction-only command set is verified.
- [ ] Required circulation is reduced only to the configured outage baseline.
- [ ] Pool/Spa/features/light reduction behavior is verified.
- [ ] Grid return causes fresh reevaluation, not stale-state restoration.
- [ ] Restart during outage cannot replay stale authority.

## Before enabling sanitation

- [ ] Body, duration, and pump target are correct.
- [ ] Session is bounded and body-specific.
- [ ] Grid outage preempts sanitation.
- [ ] Manual body OFF cancels the session.
- [ ] Filtration credit semantics are correct.
- [ ] Completion and hand-back are verified.

## Pump target / RPM-GPM capability changes

- [ ] Adapter positively proves the controllable unit.
- [ ] GPM telemetry is not mistaken for GPM setpoint capability.
- [ ] Trustworthy native min/max limits are known before GPM is exposed.
- [ ] Unknown capability fails closed to the proven unit, normally RPM.
- [ ] Manual override and return-to-baseline hand-back are tested per session.
- [ ] Session boundaries clear non-durable manual target overrides.

## Physical commissioning evidence

For every important transition capture:

- [ ] pre-command authoritative state;
- [ ] accepted command identity and time;
- [ ] later authoritative consequence;
- [ ] ownership/provenance result;
- [ ] final converged state;
- [ ] any unexpected native controller behavior.

## STOP conditions

Stop physical commissioning if:

- [ ] body/topology evidence is contradictory;
- [ ] PoolOS repeatedly commands without converging;
- [ ] verification chronology is ambiguous;
- [ ] pump/source/body state cannot be confidently attributed;
- [ ] equipment behaves outside the accepted safety envelope;
- [ ] native controller state cannot be recovered manually.

A STOP condition is not evidence of operator takeover and must not be converted into fabricated ownership.
