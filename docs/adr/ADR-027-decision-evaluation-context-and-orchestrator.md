# ADR-027: Decision Evaluation Context and Command-Free Orchestrator

## Status

Accepted for PoolOS milestone 10.12A/B.

## Decision

PoolOS uses a dedicated immutable `DecisionEvaluationContext` as the factual snapshot for
one supervisory evaluation. A `DecisionOrchestrator` validates that context, invokes the
existing explainable planner, records the result when a recorder is configured, and creates
the Home Assistant decision projection.

The orchestrator has no execution-engine or command-dispatch dependency. Plans may contain
proposed commands, but this layer cannot send them to equipment.

## Rationale

A single evaluation snapshot makes the reason for a decision explicit and gives later replay,
stability, and restart-recovery milestones a stable input boundary. Keeping orchestration
separate from actuation allows runtime behavior to be tested before equipment control is
introduced.

## Consequences

- Context identifiers, triggers, modes, schema versions, and previous decisions are embedded
  in decision metadata.
- Context blockers stop planning before a plan or Flight Recorder entry is created.
- Home Assistant projection is available only when the decision was recorded.
- The existing `RuntimeContext` remains unchanged because it models runtime queue mechanics,
  not decision facts.
