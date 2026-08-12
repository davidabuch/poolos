# ADR-095 — Observation Source Selection Architecture

## Status

Accepted for milestone 12.0C4.

## Context

PoolOS currently receives its authoritative Home Assistant observation snapshot from configured Home Assistant entities while an independent, PoolOS-owned IntelliCenter read-only transport produces native canonical observations in shadow mode.

Milestones 12.0C1 through 12.0C3 intentionally keep those roles separate. The native path exists for raw discovery, semantic calibration, parity comparison, and sustained commissioning evidence. It has no observation authority, command authority, command delivery, or physical delivery.

The next architectural step is to define a stable source-selection boundary without changing the currently deployed 12.0C3 commissioning experiment or prematurely granting the native source authority.

## Decision

PoolOS introduces a typed observation-source selection boundary with two source identities:

- `HOME_ASSISTANT`
- `NATIVE_INTELLICENTER`

The boundary separates observation provenance from command authority and from transport delivery.

### Production rule for 12.0C4

Home Assistant remains the only production-authoritative observation source.

A production request for `NATIVE_INTELLICENTER` is structurally rejected for authority purposes even if the native source is available and healthy. If Home Assistant remains available, the selection result explicitly falls back to Home Assistant. If Home Assistant is unavailable, selection fails closed rather than silently elevating native evidence.

There is no configuration-flow or options-flow control that enables native production selection in 12.0C4.

### Candidate rule

Native IntelliCenter may be selected as a non-authoritative candidate for unit tests, architecture validation, and future commissioning composition. Candidate selection never grants observation authority and never enables command or physical delivery.

### Provider contract

A read-only provider contract returns an immutable source read containing:

- fixed source identity;
- timezone-aware generation timestamp;
- availability;
- an opaque canonical payload;
- optional normalized failure reason.

The selector does not inspect or mutate observation values. Existing Home Assistant and native canonical models therefore remain independently testable and can later be adapted to the boundary without changing their semantic mappings.

## Safety invariants

Milestone 12.0C4 enforces all of the following:

1. Native availability alone can never grant production observation authority.
2. Home Assistant remains the sole production-authoritative observation source.
3. Source selection grants no command authority.
4. Command delivery remains disabled.
5. Physical delivery remains disabled.
6. No Home Assistant service call is introduced.
7. No IntelliCenter mutation operation is introduced.
8. The independent IntelliCenter transport remains read-only.
9. 12.0C3 parity history, thresholds, tolerances, retention, and continuity semantics are unchanged.
10. The currently deployed Home Assistant coordinator is not modified by this milestone.

## Why the coordinator is intentionally unchanged

12.0C3 is actively collecting a 72-hour sustained native-vs-Home-Assistant parity record. Deploying or rewiring the coordinator during that evidence window would create unnecessary experimental risk.

12.0C4 therefore establishes and tests the source-selection contract in the PoolOS core package without inserting it into the live coordinator. The coordinator continues to build authoritative observations from Home Assistant exactly as before.

A later milestone may compose this boundary into Home Assistant only after the commissioning evidence has been reviewed and any required semantic corrections have been completed.

## Consequences

### Positive

- Source-selection semantics are explicit before authority changes.
- Native-source composition can be tested without deployment.
- Production behavior fails closed.
- Observation provenance is decoupled from command authority.
- C3 evidence collection is not disturbed.

### Tradeoffs

- C4 does not yet make native observations selectable in the deployed Home Assistant integration.
- A later milestone must adapt the existing Home Assistant and native snapshots into the provider contract and expose selection diagnostics in Home Assistant.

## Follow-on milestones

After the 72-hour C3 evidence review:

1. Resolve any persistent parity or semantic issues supported by evidence.
2. Compose the source-selection boundary into the Home Assistant coordinator behind explicit commissioning controls.
3. Permit native observation selection only after manual approval and additional fail-closed tests.
4. Keep command authority and command delivery as separate, later safety decisions.

`READY_FOR_REVIEW` from sustained parity commissioning remains evidence readiness only and does not itself authorize source switching.
