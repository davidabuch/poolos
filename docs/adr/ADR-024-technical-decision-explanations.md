# ADR-024: Technical Decision Explanations

## Status

Accepted

## Context

The human-readable renderer intentionally hides implementation detail. Engineering,
simulation, regression, and Flight Recorder workflows instead require a complete and
stable diagnostic representation of the canonical decision graph.

The diagnostic representation must remain separate from decision evaluation. It must
not reinterpret scores, rerun checks, or depend on pool-specific policy.

## Decision

PoolOS will provide a deterministic `TechnicalExplanationRenderer` that converts one
`DecisionExplanation` into an immutable `TechnicalExplanation`.

The output contains ordered sections for:

- decision identity, evaluation time, goal, outcome, selected alternative, confidence,
  summary, and next-change trigger;
- every evidence item, including provenance, observation time, and metadata;
- every check, including status, blocking state, reason, and evidence references;
- every alternative in canonical rank order, including status, score, reasons, and
  metadata;
- decision-level metadata in sorted key order.

The renderer uses stable formatting, fixed numeric precision, ISO-8601 timestamps, and
sorted metadata. Empty sections are explicit by default and may be omitted through an
immutable renderer option.

## Consequences

- Flight Recorder and debugging tools receive reproducible diagnostic text.
- Snapshot and regression tests can compare technical explanations byte-for-byte.
- Human-facing wording remains independent from engineering diagnostics.
- Rendering does not alter or supplement the canonical decision graph.
