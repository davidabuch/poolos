# PoolOS Runtime Memory — Milestone 9.5

Runtime Memory is a bounded, hardware-independent record of how this specific
pool installation behaves. It provides observations and predictions only; it
never issues commands.

## Capabilities

- Rolling numeric observations with configurable per-metric retention
- Mean, median, range, latest value, and 95th-percentile summaries
- Conservative adaptive delay recommendations
- Snapshot and restore hooks for future persistence adapters
- Runtime metrics for cycle duration, command outcome, and command latency
- Reconciliation response-time learning keyed by logical command target

## Metric examples

- `runtime.cycle_seconds`
- `execution.pump.rpm.latency_seconds`
- `execution.pump.rpm.success`
- `reconciliation.pump.response_seconds`
- `pump.prime_seconds`
- `heater.ignition_seconds`
- `valve.move_seconds`

The memory layer is deliberately small. A future SQLite, Home Assistant, or
other persistence adapter can save and restore `MemorySample` objects without
changing Runtime Memory itself.
