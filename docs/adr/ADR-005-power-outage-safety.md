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

Activate after the sensor is off for two seconds.

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
The present HA observation adapter maps the configured grid-status entity
directly and does not yet implement the required two-second confirmation.
No production decision/runtime surface currently consumes a confirmed outage
to create this recommendation. Confirmation, command-free runtime integration,
and any later physical commissioning must be implemented together before this
decision can be treated as active PoolOS behavior.

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
