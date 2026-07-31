# ADR-025: Explainable Planning and Decision Flight Recorder

## Status

Accepted

## Context

Milestones 10.11A through 10.11D defined immutable decision models, deterministic
alternative ranking, and human and technical renderers. Those components remained
standalone. PoolOS still needed one orchestration boundary that creates a plan, ranks
its candidate strategies, produces a canonical explanation, renders both views, and
records the result without allowing persistence concerns to leak into the planner.

## Decision

PoolOS introduces an `ExplainablePlanner` composition service. It wraps the existing
`Planner`, `AlternativeRankingEngine`, explanation renderers, and an optional
`DecisionRecorder` protocol.

The service:

1. creates the immutable plan through the existing planner;
2. ranks domain-supplied normalized alternatives;
3. derives the canonical outcome from blocking checks and ranking feasibility;
4. builds one `DecisionExplanation` linked to the plan and objective;
5. renders human and technical explanations; and
6. appends an immutable `DecisionFlightRecord` when a recorder is configured.

The initial recorder is intentionally in-memory and append-only. It provides stable
sequence numbers, plan and objective histories, and deterministic compact JSON export.
Durable storage can implement the same protocol later without changing planner logic.

Blocked or deferred decisions preserve the ranking order but normalize any ranking
winner from `selected` to `feasible`, because the canonical decision model forbids a
selected alternative when the final decision outcome is not selected.

## Consequences

- Planning remains hardware-independent and backward compatible.
- Decision provenance is generated at the planning boundary rather than reconstructed
  after execution.
- Flight Recorder persistence is optional and dependency-injected.
- Revisions can be queried by objective while individual decisions remain linked to a
  specific immutable plan.
- Home Assistant publication can consume recorder records in the next milestone.
