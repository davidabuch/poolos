# ADR-105: Command-Free Thermal Runtime Readiness

Status: accepted

## Context

ADR-102 defines deterministic coupled thermal plans and ADR-103 defines a
tightly bounded, default-deny live execution capability. Before supervised
commissioning, operators need current evidence showing what PoolOS would plan,
whether current Phase 2 authorization would pass, and which technical gates
remain blocked. Connecting coordinator refreshes to the execution engine would
create unreviewed automatic actuation.

## Decision

PoolOS adds a side-effect-free thermal runtime evaluator. It consumes direct
typed requested modes plus the current authoritative native IntelliCenter
snapshot, observation freshness and immediate health, native/manual transport
availability, and the existing native-configuration guard. It reuses the
existing Pool and Hot Tub policy engines, ADR-102 planner, and ADR-103
authorization rules; Home Assistant code does not duplicate thermal policy.

Each body publishes two deliberately different results:

- actual dry-run authorization applies the effective thermal kill switch,
  one-body commissioning scope, and every technical gate; and
- technical commissioning preflight omits only the operator enable/scope
  gates and returns blocker strings, not a delivery-capable authorization.

The HA integration exposes a `Thermal Live Execution` configuration switch,
which is always effectively off after every integration start, and a restorable
`Thermal Commissioning Scope` select with exactly Disabled, Pool, and Hot Tub.
Changing either recomputes diagnostics only. Requested modes flow directly
from the existing body selectors into typed runtime state rather than being
read back from PoolOS's own HA entity states.

Native/coordinator updates recompute immutable current assessments and notify
listeners. Three compact diagnostic sensors expose global, Pool, and Hot Tub
summaries with bounded rationale, evidence, blockers, identities, and current
requested/planned/effective state. No history is placed in HA attributes.

## Safety consequences

- Phase 3 does not import, instantiate, schedule, or invoke
  `ThermalLiveExecutionEngine` or any delivery port.
- Startup, restoration, native updates, coordinator refreshes, switch changes,
  scope changes, and requested-mode changes issue zero physical commands.
- Immediate current health—not the durable incident latch—gates both actual
  authorization and technical preflight.
- Missing or stale native truth is not replaced by secondary HA evidence.
- The general authorization model and ADR-103 equipment/operation allowlists
  remain unchanged.
- Spillway, filtration, temperature-probe, and grid-outage execution remain
  non-live, and IntelliCenter configuration is never rewritten.
