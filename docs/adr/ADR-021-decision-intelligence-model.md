# ADR-021: Immutable Decision Intelligence Model

## Status

Accepted for Milestone 10.11A.

## Context

PoolOS already produces deterministic plans, policy decisions, validation results, energy optimizations, and forecast assessments. Those components expose useful reasons, but they do not yet share one canonical structure capable of answering what facts were considered, which checks passed or blocked action, which alternatives were evaluated, and why a final action was selected.

Explainability must not be reconstructed later from log messages. It must be a first-class immutable output of decision evaluation so that the Home Assistant adapter, Flight Recorder, dashboards, and future natural-language renderers all consume the same facts.

## Decision

Introduce `poolos.decision_intelligence` with immutable, provider-independent models:

- `DecisionEvidence` for traceable input facts
- `DecisionCheck` for policy, safety, ownership, and constraint results
- `DecisionAlternative` for ranked candidate actions
- `DecisionExplanation` for the complete decision graph
- typed enums for outcomes, evidence kinds, check states, and alternative states

The model validates referential integrity, selected-alternative consistency, blocking outcomes, unique identifiers, rank uniqueness, confidence bounds, and timezone-aware timestamps. Metadata is exposed through read-only mappings.

Milestone 10.11A defines only the canonical model. It does not rank alternatives, generate prose, write Flight Recorder events, publish Home Assistant entities, or issue equipment commands.

## Consequences

Positive consequences:

- Every future decision can carry a stable audit structure.
- Human and technical explanations can be rendered without changing decision logic.
- Rejected alternatives become inspectable and testable.
- Flight Recorder and dashboards can share one canonical schema.
- Explainability remains deterministic and independent of external AI services.

Tradeoffs:

- Existing planners must later be adapted to populate this richer model.
- Explanation data increases the size of persisted decision records.
- Schema evolution must remain backward compatible once Flight Recorder integration begins.
