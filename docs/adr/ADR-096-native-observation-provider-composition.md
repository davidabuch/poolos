# ADR-096 — Native Observation Provider Composition

## Status

Accepted for milestone 12.0C5.

## Context

ADR-095 introduced a typed observation-source selection boundary while keeping Home Assistant as the only production-authoritative observation source. The native IntelliCenter path already produces `NativeIntelliCenterObservationSnapshot`, an immutable canonical snapshot containing mapped `PoolObservation` values, source availability, generation time, missing concepts, and an optional failure reason.

The remaining preparatory gap is to prove that this native canonical snapshot can participate in the generic provider/source-selection architecture without changing Home Assistant runtime behavior or granting native observations authority.

12.0C3 sustained native parity commissioning is still collecting live evidence. This milestone must therefore remain code-and-test-only and must not alter the deployed Home Assistant coordinator or its commissioning persistence path.

## Decision

PoolOS introduces a concrete `NativeIntelliCenterObservationProvider` that adapts an existing `NativeIntelliCenterObservationSnapshot` into the generic `ObservationSourceRead` contract established by ADR-095.

### Provider mapping

For an `AVAILABLE` native snapshot:

- source is `NATIVE_INTELLICENTER`;
- source-read availability is `true`;
- `generated_at` is preserved exactly;
- the original immutable native snapshot is preserved as the payload;
- no failure reason is emitted.

For `INITIALIZING` or `UNAVAILABLE` snapshots:

- source remains `NATIVE_INTELLICENTER`;
- source-read availability is `false`;
- no payload is exposed;
- the existing normalized failure reason is preserved when present;
- otherwise a stable non-authoritative provider reason is emitted.

The provider does not inspect, recalculate, modify, merge, or reinterpret canonical observation values.

### Candidate composition

A small composition boundary combines the provider read with the existing non-authoritative candidate selector.

An available native source may therefore be selected as candidate evidence, but the composition enforces all of the following:

- `authoritative_observation_source = false`;
- `command_authority = none`;
- `command_delivery_enabled = false`;
- `physical_delivery_enabled = false`;
- production native selection remains disabled.

Unavailable or initializing native evidence is not selected as a candidate.

### Production selection remains unchanged

12.0C5 does not modify `select_production_observation_source()`.

Even after a healthy native provider has been successfully composed, a production request for native observations still cannot elevate native authority. If Home Assistant is available, production selection falls back to Home Assistant. If Home Assistant is unavailable, production selection fails closed.

## Safety invariants

Milestone 12.0C5 preserves these invariants:

1. Home Assistant remains the sole production-authoritative observation source.
2. Native provider availability does not grant production observation authority.
3. Candidate composition is always non-authoritative.
4. Source composition grants no command authority.
5. Command delivery remains disabled.
6. Physical delivery remains disabled.
7. No Home Assistant service call is introduced.
8. No IntelliCenter mutation operation is introduced.
9. No config-flow or options-flow source selector is introduced.
10. The Home Assistant coordinator is unchanged.
11. 12.0C3 parity history, tolerances, retention, continuity, and persistence behavior are unchanged.
12. The existing native semantic mapping remains unchanged.

## Why Home Assistant composition is deferred

The purpose of C5 is to prove native-provider compatibility with the source-selection architecture while the active C3 commissioning experiment remains undisturbed.

Wiring source selection into the Home Assistant coordinator, publishing source-selection controls, or allowing native observations to feed the supervisory runtime are separate later commissioning decisions. Those changes require review of the sustained C3 evidence first.

## Consequences

### Positive

- Native canonical observations now have a concrete typed provider path.
- The original immutable native snapshot remains intact across composition.
- Initializing and unavailable states fail closed with stable diagnostics.
- Candidate selection can be exercised end-to-end in tests.
- Production authority remains structurally unchanged.
- No Home Assistant deployment is required.

### Tradeoffs

- C5 still does not make native observations selectable in Home Assistant.
- The production coordinator continues to read authoritative observations directly from Home Assistant.
- A later milestone must decide how and when provider composition enters the deployed coordinator.

## Follow-on

After the 72-hour C3 commissioning evidence is reviewed, PoolOS can decide whether the next step should be semantic correction, source-selection diagnostics in Home Assistant, or explicitly gated native-source commissioning.

`READY_FOR_REVIEW` remains an evidence-readiness state only and does not authorize native source switching.
