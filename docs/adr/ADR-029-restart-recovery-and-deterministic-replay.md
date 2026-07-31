# ADR-029: Restart Recovery and Deterministic Replay

## Status

Accepted for PoolOS milestone 10.12E.

## Context

A supervisory runtime must survive process restarts without blindly restoring stale intended
state. The last decision remains useful as comparison history, but current observations,
forecasts, policies, goals, and safety conditions are authoritative after restart.

The same command-free evaluation path should also support deterministic replay so recorded
factual contexts can be regression tested against stable decision signatures.

## Decision

PoolOS introduces `RestartRecoveryEngine` and `DecisionReplayEngine`.

Restart recovery:

1. Reads the latest immutable Flight Recorder decision.
2. Requires a `restart_recovery` evaluation context.
3. Verifies that the context references the latest known decision.
4. Reevaluates current facts through the normal `DecisionOrchestrator`.
5. Retains an equivalent decision or appends a materially superseding decision.
6. Does not restore commands, desired equipment state, or prior actuator intent.
7. Does not append a record when the current context is blocked.

Deterministic replay:

1. Replays ordered evaluation contexts through the same orchestrator.
2. Carries the active decision forward between replay steps.
3. Verifies optional stable signatures consisting of outcome, selected alternative,
   stability disposition, and orchestration status.
4. Has no command dispatcher or execution-engine dependency.

## Consequences

- Restart behavior is based on current facts rather than stale intent.
- Equivalent decisions do not create duplicate Flight Recorder entries.
- Changed facts create an auditable superseding decision.
- Golden scenarios can detect behavioral drift without issuing equipment commands.
- Durable context persistence remains a separate infrastructure concern.
