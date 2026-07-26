# PoolOS Hardware Abstraction Layer

Milestone 10.1 defines the stable boundary between the PoolOS runtime and all
physical pool equipment.

## Layering

```text
Applications
    -> Runtime
        -> HAL equipment contracts
            -> Vendor adapter
                -> Transport
                    -> Hardware
```

Each layer knows only the layer directly below it. Runtime code never imports
Pentair, Home Assistant, serial, or RS-485 implementation details.

## Equipment contracts

The HAL includes vendor-neutral interfaces for pumps, heaters, valves, filters,
lights, chlorinators, covers, and sensors. Capabilities are negotiated before
optional operations are used. A single-speed pump can implement start/stop
without pretending to support RPM control.

## Command receipts and verification

A command receipt distinguishes accepted, sent, acknowledged, verified,
rejected, failed, and timed-out states. A transport acknowledgement is not the
same as physical verification. The existing PoolOS reconciliation layer remains
responsible for comparing desired and observed state.

## Adapters

A vendor adapter translates stable PoolOS concepts into vendor semantics. Every
adapter publishes identity, version, supported equipment classes, lifecycle,
discovery, and health. Adapters can be replaced in the registry without changing
runtime or application code.

## Transports

Transports only move data. HAL 10.1 includes:

- an operational in-memory simulator transport;
- an explicit Home Assistant transport boundary, intentionally unimplemented;
- an explicit RS-485 transport boundary, intentionally unimplemented.

No hardware dongle, serial library, Home Assistant installation, or Pentair
protocol is assumed.

## Filter instrumentation

Filter pressure and flow are optional observations. An analog pressure gauge is
not exposed as digital PSI. Filter health is not a HAL capability; it remains a
calculated or learned PoolOS metric with evidence and confidence.

## Adapter health

Standard states are unknown, initializing, connected, degraded, read-only,
disconnected, and error. Health identifies whether an adapter is readable or
writable without conflating degraded communication with equipment faults.
