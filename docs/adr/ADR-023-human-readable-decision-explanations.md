# ADR-023: Human-Readable Decision Explanations

## Status

Accepted

## Context

The immutable decision-intelligence model records complete facts, checks, alternatives,
and outcomes. Operators also need a concise explanation that can be displayed in Home
Assistant notifications and dashboards without exposing internal scoring mechanics.

The future technical renderer will serve diagnostics and engineering workflows. The
human renderer therefore needs its own deliberately smaller contract.

## Decision

PoolOS will provide a deterministic `HumanExplanationRenderer` that converts one
`DecisionExplanation` into an immutable `HumanReadableExplanation` containing:

- a headline derived from the canonical decision summary;
- ordered plain-language detail sentences;
- one display-ready `text` value.

The renderer communicates the outcome, selected alternative, important failed or
unknown checks, a bounded number of rejected alternatives, the next material change,
and optional confidence. It does not expose criterion weights or score contributions.

Rendering configuration is immutable. Alternative presentation follows canonical rank
order, so identical decision inputs always produce identical text.

## Consequences

- Home Assistant and notification layers receive stable human-facing text.
- Human wording remains separate from technical diagnostics.
- The canonical decision graph remains the source of truth.
- Future localization can replace the renderer without changing decision evaluation.
