# ADR-102: Command-Disabled Coupled Thermal Execution Planning

Status: accepted

## Context

PoolOS already selects pool and spa heat sources and their known-good pump RPM
baselines. The execution architecture already accepts canonical operations,
constructs ordered plans, verifies observations, and rejects live or physical
execution. What was missing was a narrow bridge that preserved one thermal
policy decision as an auditable coupled physical state and a bounded Pentair
translation for that state.

The commissioned IntelliCenter identities are Pool `B1101`, Hot Tub `B1202`,
no heater `00000`, gas `H0001`, and solar `H0002`. `HEATER` is selected-source
truth. `HTMODE` describes current heating activity and must never be written or
required to prove source selection.

## Decision

`ThermalDesiredState` preserves the requested policy mode, selected physical
source, required RPM, reason codes, criteria, rationale, and source evidence.
`ThermalExecutionPlanBuilder` compares it with explicit native current state and
produces canonical `SetHeatMode` and `SetPumpSpeed` operations plus existing
`ExecutionStepSpecification` values. The result remains authority `none` and
command delivery disabled.

Ordering establishes or raises required flow before enabling a heat source. A
transition that lowers RPM selects the new source first, then lowers RPM.
Exiting heat selects Off without assuming ordinary circulation should stop.
Already-converged states produce no operations. Planning and verification use
the same inclusive 25-RPM convergence tolerance. Missing authoritative RPM for
an active Solar or Gas state, stale/degraded evidence, contradictions, or a
permission veto produce a blocked plan. Off has no thermal-RPM requirement and
deselects only the heat source; it never implies stopping circulation.

Evidence required to select or continue Solar/Gas remains fail-closed. Once the
policy has selected Off, unavailable collector evidence that is irrelevant to
safe de-selection does not preserve an active heat source. Explicit unusable
evidence, contradictions, and permission vetoes remain blocking.

`SetHeatMode` accepts only Pool or Hot Tub and only Off, Solar, or Gas. Pentair
translation emits exactly one logical `body.set_heater` command using the
commissioned body/heater matrix. Solar Preferred is policy intent and cannot
cross the physical translation boundary. Because the vendor endpoint also
accepts already-created `VendorCommand` values, it independently validates the
same narrow body/heater matrix before physical delivery. This defense does not
generalize into an arbitrary IntelliCenter-property API.

Requested mode, selected native source, and active physical execution are
separate state. Pool and Hot Tub requested modes and target temperatures may be
configured while either or both bodies are inactive. Direct Off/Solar/Gas
selection may persist the commissioned native `HEATER` property without
changing BODY `STATUS`; it does not start circulation. Body activity remains a
physical-policy input and may still block an autonomous heating plan.

Expected source convergence is `HEATER == 00000/H0001/H0002`; a fresh wrong
`HEATER` fails verification immediately and can never opt into relaxed behavior
through metadata. Expected RPM convergence uses authoritative native
`pump.rpm`; an explicit 25-RPM tolerance and bounded pre-deadline settling apply
only to typed `SetPumpSpeed` steps whose sole expectation is `pump.rpm`.
`HTMODE` may be retained as context but is not selected-source proof.

The commissioned Spillway/Waterfall operating baseline is 2900 RPM. Current HA
manual control observes `waterfall.active` and switches only circuit `FTR01`,
with Pool activity as a parent interlock; it does not yet coordinate pump RPM.
The IntelliCenter Spillway RPM preset must remain until a future coupled plan is
implemented and live-commissioned. Such a plan must establish sufficient RPM
before enabling Spillway and, on exit, return RPM selection to the other active
PoolOS requirement rather than force a fixed fallback.

## Safety consequences

- No Home Assistant, IntelliCenter, network, or equipment call is introduced.
- Existing simulator-only authorization continues rejecting live runtime,
  physical delivery, and non-simulator endpoints.
- Restart does not resume a thermal plan; fresh evaluation and native evidence
  are required.
- Native Solar Preferred, RPM assignments, and schedules remain read-only
  conflicts. They are not rewritten or removed.
- Inactive-body `HEATER` preselection is represented and unit-tested, but still
  requires explicit live commissioning before autonomous operation relies on
  that controller behavior.
- Pentair preset RPM values must remain until narrowly scoped live delivery is
  separately implemented and commissioned for every affected operating mode.
