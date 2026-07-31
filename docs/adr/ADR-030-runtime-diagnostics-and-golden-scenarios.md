# ADR-030 — Supervisory Runtime Diagnostics and Golden Scenarios

## Status

Accepted and implemented by PoolOS milestone 10.12F/G.

## Context

The command-free supervisory runtime can evaluate immutable contexts, coalesce triggers,
stabilize decisions, recover after restart, and replay historical scenarios. Operators still
need a concise runtime heartbeat, while developers need permanent end-to-end regression
scenarios that verify the complete supervisory path.

Diagnostics must not become part of the decision or actuation path. A diagnostics failure
must never block planning, change a decision, or send an equipment command. Golden
scenarios must be deterministic and reusable as the architecture evolves.

## Decision

PoolOS introduces an observational `SupervisoryRuntimeMonitor` that consumes completed
orchestration results and emits immutable `SupervisoryRuntimeSnapshot` values. Snapshots
include evaluation count, trigger, status, context validity, active and previous decision IDs,
stability disposition, recovery and replay status, blockers, next reevaluation, and derived
health.

A separate Home Assistant projection maps snapshots into the live `poolos_runtime_*`
namespace. Publication is transport-neutral and idempotent. The diagnostic module is not
re-exported through the Home Assistant package root because doing so would create an
unnecessary circular dependency with the orchestrator.

PoolOS also introduces a generic `GoldenScenarioSuite`. Scenarios are executed in stable ID
order, failures are isolated and reported, and the suite never executes equipment commands.
Permanent tests cover normal decisions, equivalent reevaluation, blocked contexts,
material supersession, deterministic replay, and live/simulation namespace isolation.

## Consequences

- Runtime diagnostics remain observational and cannot affect planning or actuation.
- Home Assistant receives a stable supervisory heartbeat without confusing it with
  simulated telemetry.
- Equivalent evaluations and blocked contexts are visible operationally.
- Golden scenarios become permanent release gates for future runtime changes.
- Additional diagnostics or scenarios can be added without modifying the core planner.
