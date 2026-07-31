# ADR-028: Reevaluation Triggers and Decision Stability

## Status

Accepted for Milestones 10.12C and 10.12D.

## Context

A supervisory runtime may receive several reasons to evaluate at nearly the same time. Running one
cycle for every notification creates redundant plans, recorder entries, and Home Assistant updates.
Even when reevaluation is appropriate, a newly generated plan should not replace the active decision
unless the operational result changes materially.

## Decision

PoolOS introduces typed evaluation-trigger requests with explicit urgency. Pending requests are
coalesced deterministically by urgency, trigger precedence, timestamp, source, and reason. The
coalesced batch preserves every original reason while selecting one primary trigger for the immutable
evaluation context.

PoolOS also introduces a decision-stability engine. It compares a proposed decision with the active
Flight Recorder decision using operational semantics: goal, outcome, selected alternative, and active
blocking checks. Equivalent decisions retain the active record. Materially different proposals may
also be retained while a configured minimum lifetime is active or while confidence improvement is
below a configured hysteresis threshold.

The command-free orchestrator creates an unrecorded proposal first. Stability is evaluated before any
append or Home Assistant update. Only accepted initial or superseding decisions are recorded. A
retained decision reuses the active Flight Recorder record and its Home Assistant projection.

## Consequences

- Bursty trigger inputs produce one deterministic evaluation cycle.
- Equivalent reevaluations do not create Flight Recorder churn.
- Minimum lifetime and confidence hysteresis are explicit, testable policy values.
- The prior decision remains the active source of truth when a proposal is retained.
- The orchestrator remains unable to dispatch equipment commands.
- Restart recovery can reuse the same active-record and stability boundary in Milestone 10.12E.
