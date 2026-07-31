# ADR-022: Deterministic Alternative Ranking

## Status

Accepted for Milestone 10.11B.

## Context

Milestone 10.11A established an immutable decision-explanation graph, including ranked alternatives, but intentionally did not define how alternatives are scored or selected. PoolOS now needs a reusable ranking mechanism that is deterministic, auditable, independent of vendor integrations, and neutral about pool-specific policy.

The ranking layer must not independently decide whether a pool action is safe, owned, permitted, or capable of satisfying a goal. Those facts belong to upstream domain, policy, ownership, safety, forecast, and planning components. The ranking layer should compare normalized facts supplied by those components.

## Decision

Introduce `poolos.alternative_ranking` with immutable models for:

- `RankingCriterion`, defining a scoring dimension and positive relative weight
- `AlternativeCandidate`, carrying normalized scores, feasibility, tie-break priority, reasons, and metadata
- `CriterionContribution`, preserving each weighted score contribution
- `RankedCandidate`, representing one ordered result
- `RankingResult`, representing the full ranking and optional selection
- `AlternativeRankingEngine`, performing deterministic weighted ranking

Every criterion score is normalized to the closed interval from zero to one. Criterion weights are normalized to sum to one. Candidates must provide exactly the configured criteria.

Ordering is deterministic:

1. feasible candidates before infeasible candidates
2. higher weighted score first
3. lower explicit priority value first
4. lexicographically smaller stable alternative ID first

Only the highest-ranked feasible candidate is selected. Infeasible candidates remain in the ranking for auditability but can never be selected. Results convert directly into the canonical `DecisionAlternative` model from ADR-021.

Milestone 10.11B does not define pool-specific criteria, generate human or technical prose, write Flight Recorder events, publish Home Assistant entities, or issue equipment commands.

## Consequences

Positive consequences:

- Candidate comparison is deterministic and unit-testable.
- Scoring policy remains explicit at the call site through criteria and weights.
- Every score can be reconstructed from traceable criterion contributions.
- Infeasible alternatives remain visible without risking accidental selection.
- Ranking results integrate directly with the decision-intelligence graph.

Tradeoffs:

- Upstream components must normalize domain facts into zero-to-one scores.
- Criterion selection and weighting remain policy decisions that require separate profiles or adapters.
- Weighted scoring cannot replace hard safety, ownership, or feasibility checks.
