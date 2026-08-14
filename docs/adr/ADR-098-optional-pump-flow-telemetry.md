# ADR-098 — Optional Pump Flow Telemetry

## Status

Accepted for PoolOS milestone 12.0C5.2 pending validation.

## Context

Commissioning on a Pentair variable-speed (VS) pump showed RPM and electrical power changing appropriately when the High Speed circuit was enabled while the reported GPM value remained fixed at 55. A VS-only pump does not provide the same trustworthy flow telemetry expected from a VSF pump or a dedicated flow sensor. Requiring a GPM entity can therefore force installations to map a nominal or non-measured value and can make that value appear more authoritative than the hardware supports.

## Decision

1. `pump_gpm_entity` becomes an optional Home Assistant observation mapping.
2. The canonical `pump.gpm` concept remains supported for VSF pumps, dedicated flow sensors, or other installations with meaningful measured flow.
3. If no GPM entity is configured, PoolOS simply omits `pump.gpm` from the Home Assistant observation snapshot; missing GPM does not make the snapshot unhealthy.
4. The default PoolOS Operations Center dashboard no longer displays a GPM gauge or GPM history series. Operators may add the sensor manually when a trustworthy flow source is configured.
5. RPM and pump power remain required commissioning inputs.

## Safety and commissioning boundary

This change does not alter observation authority, native-source selection, parity tolerances, IntelliCenter transport behavior, command authority, command delivery, or physical delivery. It is repository-only during the active 72-hour sustained parity run and must not be deployed until that observation window is complete or explicitly restarted.
