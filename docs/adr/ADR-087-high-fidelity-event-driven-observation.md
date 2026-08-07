# ADR-087 — High-Fidelity Event-Driven Home Assistant Observation

## Status

Accepted for PoolOS milestone 11.4A.

## Context

PoolOS 0.9.0 could observe a useful but narrow set of Home Assistant entity states on a
30-second coordinator interval. Before live commissioning, the observation boundary must preserve
the variables needed to learn real pool and spa thermal/hydraulic behavior without copying Pentair
schedules or preset RPM configuration.

The installed IntelliCenter/HomeKit thermostat entities also have installation-specific semantics:
HA `hvac_mode=heat` means that the body/pump is enabled. It does **not** prove that a heat source is
active. `hvac_action=heating` represents active heating demand, while `idle` means the body is
running without active heating demand.

## Decision

PoolOS will use event-driven state observation for configured Home Assistant sources plus the
existing 30-second coordinator refresh as a periodic reconciliation/backstop.

The commissioned observation set includes:

- pool/spa body-enabled state derived from thermostat `Status`;
- pool/spa active heating demand derived from thermostat `hvac_action`;
- pool/spa current and target temperatures;
- raw thermostat HVAC mode, HVAC action, Pentair `HEATER`, and `HTMODE` evidence;
- actual pump RPM, GPM, and watts;
- generic Pentair water temperature, solar/roof temperature, and air temperature;
- actual solar engagement and gas-heater activity;
- pool/spa command/circuit state;
- optional Solar Preferred, waterfall/spillway, jets, and slide context.

Thermostat attribute observations bind directly to the HA entity attributes. Template sensors are
not required. Attribute provenance is preserved in the canonical `source_id`.

Pentair schedules, configured pool/solar/heat speed presets, and freeze-learning logic are not part
of this milestone. Solar Preferred is explanatory evidence only and is not a PoolOS control-policy
dependency.

The durable recorder continues to suppress insignificant numeric noise and unchanged snapshots.
Meaningful state transitions are therefore timestamped at HA event time while periodic checkpoints
retain trend continuity and recovery evidence.

## Consequences

- PoolOS can collect high-resolution startup, valve/solar, RPM, GPM, and equipment-state evidence.
- Pool and spa solar effectiveness can be learned independently from physical outcome data.
- A 30-second reconciliation interval no longer defines observation latency.
- High-frequency sensor noise is bounded by recorder significance thresholds.
- The integration remains OBSERVE/SHADOW only, authority NONE, command delivery disabled, and
  contains no Home Assistant equipment service call or physical actuation path.
