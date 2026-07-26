# Pentair Domain

Milestone 10.2 gives PoolOS a stable, transport-independent vocabulary for
Pentair automation systems. It does **not** communicate with a panel.

## Architectural boundary

```text
PoolOS Runtime
    -> HAL
        -> Pentair translation/adapter (future milestone)
            -> Transport: Home Assistant, TCP, or RS-485 (future milestones)
```

The Pentair domain must not contain Home Assistant entity IDs, serial device
paths, IP addresses, sockets, protocol bytes, or command retry logic.

## Modeled concepts

- Controller families, including IntelliCenter
- Bodies and their body circuits
- Relay, feature, virtual, body, and grouped circuits
- Pump control modes and circuit-linked setpoint programs
- Heater sources and body heat selections
- Intake, return, auxiliary, and solar valve roles
- Shared pool/spa equipment topology
- Freeze-protection eligibility/state vocabulary

## Configuration versus observed truth

A Pentair pump program such as `Pool = 1800 RPM` is configuration. It is not a
measurement and must never be treated as actual pump speed. The actual RPM
telemetry remains the source of truth when it is available.

This distinction preserves the PoolOS truth model:

- configured setpoint: vendor configuration
- actual RPM: measured observation
- expected energy or flow: calculated/learned observation

## Circuits and features

Pentair frequently represents user-facing behavior through circuits. PoolOS does
not equate every circuit with a physical relay. A Pentair circuit may be:

- a physical relay
- a feature/virtual circuit
- a body selector
- a light circuit
- a circuit group

A later translation layer will map those objects into PoolOS bodies, hydraulic
routes, equipment, and features.

## Shared pool/spa equipment

`PentairSharedEquipment` explicitly models a pool and spa that share pumps,
heaters, and intake/return valves. This allows the adapter to understand Pentair
shared-equipment semantics without embedding them into the PoolOS runtime.

## Deliberately deferred

The following are outside Milestone 10.2:

- raw IntelliCenter object codes and wire values
- command translation
- state translation
- Home Assistant entity bindings
- direct TCP or RS-485 transport
- panel discovery

Those belong to the Pentair translation and transport milestones.
