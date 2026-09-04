# ADR-005: Model Power Outage Handling as a Safety Mode

- Status: Accepted
- Date: 2026-07-24

## Context

The pool equipment panel is backed by one Powerwall system. During an outage, optional high-load features should stop and required circulation should use reduced power. Independent Home Assistant automations would create multiple sources of truth and could restore stale state after utility power returns.

## Decision

Implement power outage handling as a highest-priority safety mode managed by the Command Center.

Use only:

```text
binary_sensor.1_powerwall_grid_status
```

Confirm an actual outage only after the sensor is continuously off for exactly
two seconds. The configured sensor is a persistent, event-driven Home Assistant
state source; PoolOS may establish elapsed continuity on a later evaluation of
the same fresh current state without scheduling a two-second timer.

Do not use:

```text
binary_sensor.3_powerwalls_grid_status
```

While active:

- Spa off
- Waterfall off
- Jets off
- Slide off
- Pool light off
- Normal Decision Engine determines whether circulation is required
- If circulation is required, use the configured reduced-power baseline
  (currently 1500 RPM)
- If circulation is not required, keep the pump off

Observe actual pump speed from:

```text
sensor.buch_family_vs_rpm
```

Do not alter Pentair RPM preset configuration values.

This ADR records the intended safety behavior, not current runtime authority.
The HA observation adapter maps the configured grid-status entity to the raw
`grid.outage_active` observation. The core `GridOutageConfirmationTracker` is
the single canonical command-free boundary between that raw observation and a
confirmed actual outage. It distinguishes authoritative `ON_GRID`,
`OFF_GRID_PENDING`, `CONFIRMED_OUTAGE`, and `UNKNOWN` dispositions. Missing,
stale, future, contradictory, or otherwise unusable evidence cannot confirm a
pending outage and cannot manufacture proof that a confirmed outage ended.
Only usable positive on-grid evidence ends a confirmed outage epoch.

The tracker is in-memory and deliberately does not reconstruct confirmation
from an old matching state after restart. A first off-grid evaluation after
restart begins a new two-second evidentiary epoch. It uses no sleep, polling,
timer, persistence, replay, or command path. The logical threshold time and the
later time at which PoolOS evaluates and knows confirmation are retained as
separate timestamps.

Expected-outage acknowledgments remain retrospective operator annotations.
They cannot establish or accelerate actual outage confirmation.

No production decision/runtime surface currently consumes the confirmed
assessment to create an outage recommendation or physical action. Command-free
runtime integration and any later physical commissioning remain separate work
before the intended safety behavior can be treated as active PoolOS behavior.

When grid power returns, release safety ownership and immediately reevaluate current conditions. Do not restore a pre-outage snapshot.

## Consequences

### Positive

- One source of truth
- Restart-safe behavior
- No stale-state restoration
- Extensible safety framework
- Predictable Powerwall consumption reduction

### Negative

- Depends on availability and correctness of the authoritative grid-status entity
- Requires clear behavior when the grid sensor is unavailable
- Full correctness depends on Decision Engine and Execution Engine maturity

## Rejected alternatives

### Independent Home Assistant automations

Rejected because they can conflict with normal control and are harder to make restart-safe.

### Force the pool pump on at a reduced RPM

Rejected because outage mode should constrain required circulation, not create a new circulation requirement.

### Restore previous equipment states after the outage

Rejected because previous state may be stale or inappropriate when power returns.
