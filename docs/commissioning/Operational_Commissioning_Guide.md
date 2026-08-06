# PoolOS Operational Commissioning Guide

## Purpose

This guide defines the staged process for introducing PoolOS to a real pool or
spa system. It applies first to Home Assistant and IntelliCenter, but the process
is runtime-neutral.

PoolOS begins without authority. It earns eligibility for greater authority by
producing healthy, continuous, explainable evidence. The operator explicitly
approves every increase in authority.

## Commissioning Sequence

### 1. Prepare the existing system

Before installing PoolOS:

- keep the existing controller and Home Assistant integration operational;
- inventory all entities that observe or control pool equipment;
- identify schedules, automations, applications, and physical controls that may
  change equipment state;
- document existing safety behavior and manual recovery procedures;
- confirm that observation sources expose stable entity identity and timestamps.

Do not disable existing schedules or automations during initial commissioning.

### 2. Install in OBSERVE mode

The initial installation must be read-only. PoolOS may:

- discover configured observation entities;
- normalize them into canonical observations;
- evaluate availability, quality, and freshness;
- publish PoolOS diagnostic entities;
- write observations and health evidence to the Flight Recorder.

The initial installation must not contain an enabled command-delivery path.
Possession of a Home Assistant token does not authorize actuation.

### 3. Validate observation health

Observation commissioning is complete only when:

- required entities are mapped to the correct physical equipment;
- state, units, timestamps, and availability are correct;
- restarts preserve or safely reconstruct observation state;
- manual changes from the IntelliCenter panel and application are observed;
- conflicting or unavailable data fails closed;
- Flight Recorder evidence is complete and reviewable.

### 4. Enter LEARN mode

LEARN mode may derive deterministic characteristics such as:

- pump power or flow behavior by RPM;
- heating and cooling rates under defined conditions;
- solar gain and loss;
- equipment transition latency;
- normal filtration and spa-use patterns;
- observation lag and integration reliability.

Every learned characteristic must expose its evidence window, derivation,
freshness, and confidence. Learning must not silently alter control policy.

### 5. Enter ADVISE mode

Recommendations must include:

- the proposed outcome;
- the reason and relevant policies;
- assumptions and blockers;
- alternatives considered when available;
- expected energy, runtime, temperature, or safety effect;
- evidence freshness and uncertainty.

Recommendations remain non-actuating and must be distinguishable from current
controller behavior.

### 6. Enter SHADOW mode

SHADOW mode runs the complete intended execution path without transport
delivery. For each proposed action, PoolOS should record:

- what it observed;
- what it decided;
- the plan it would authorize;
- the exact service call it would send;
- the expected observation;
- the reconciliation and recovery result it would expect.

Shadow output must be compared with actual equipment behavior over representative
conditions, including restarts, manual overrides, spa use, heating, solar,
schedules, outages, and unavailable entities.

### 7. Enter ASSIST mode by capability

ASSIST mode must be enabled one bounded capability at a time. Each capability
requires:

- explicit operator approval;
- a visible armed state;
- a narrow ownership boundary;
- preflight safety checks;
- post-delivery observation verification;
- immediate rollback;
- documented failure and manual recovery procedures.

A capability not explicitly approved remains in SHADOW mode.

### 8. Enter CONTROL mode

CONTROL mode is appropriate only after the commissioned capabilities have shown
stable assisted operation and the operator deliberately transfers authority.
Conflicting schedules and automations may be retired only after their behavior
has been replaced, validated, and documented.

## Mode Eligibility

PoolOS must distinguish between:

- **Current mode:** authority presently granted by the operator.
- **Eligible mode:** highest mode supported by current technical evidence.
- **Requested mode:** mode the operator is asking to activate.

Eligibility never changes the current mode automatically.

## Rollback

Rollback to `OBSERVE` must:

- stop new PoolOS actuation immediately;
- preserve diagnostic and Flight Recorder evidence;
- release PoolOS operational ownership safely;
- leave the underlying controller available for manual or native operation;
- require no source-code edit or repository deployment.

Rollback must not attempt to restore stale pre-PoolOS state. The current physical
state must be observed and handled explicitly.

## Commissioning Evidence Package

Before advancing a mode, retain:

- mode-readiness results;
- entity mapping and health summary;
- representative Flight Recorder evidence;
- known limitations and unresolved anomalies;
- rollback test result;
- operator approval identity and time;
- capability scope for `ASSIST` or `CONTROL`.

## Home Assistant Initial Deployment

For the first Home Assistant deployment, the existing IntelliCenter integration
remains the hardware-facing source of truth:

```text
IntelliCenter hardware
    -> Home Assistant IntelliCenter integration
    -> Home Assistant entity observations
    -> PoolOS observation bridge
    -> canonical PoolOS state, learning, and shadow decisions
```

PoolOS must not replace or disable the current integration during observation
commissioning. Later control may use the same entities as a transport boundary,
but only after explicit capability commissioning.
