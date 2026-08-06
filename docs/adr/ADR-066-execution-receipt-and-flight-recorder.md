# ADR-066: Execution Receipt and Flight Recorder Integration

## Status
Accepted

## Context
PoolOS now normalizes Home Assistant delivery acknowledgements but lacks a canonical terminal artifact that can be retained, replayed, and audited independently of transport behavior.

## Decision
Add immutable `ExecutionReceipt` evidence, a deterministic builder, and an append-only recorder contract. The builder maps canonical acknowledgement dispositions to receipt dispositions, preserves all upstream provenance, and may append the resulting receipt to an injected recorder.

The milestone performs no retry, reconciliation, network operation, or actuation. The in-memory recorder is an execution-focused append-only flight recorder and does not modify the existing decision flight recorder.

## Consequences
Every acknowledged delivery can now produce a stable terminal receipt suitable for replay, auditing, later persistence, and future closed-loop reconciliation.
