# ADR-085 — Behavioral Inference Engine

## Status

Accepted for milestone 11.3C.

## Context

Milestone 11.3B created durable, restart-safe observation evidence. PoolOS now needs to interpret that evidence without collapsing measured facts into asserted controller rules. The near-term goals are to characterize pump startup/priming behavior and Pentair solar behavior while PoolOS remains observation-only.

## Decision

PoolOS adds a vendor-independent `BehavioralInferenceEngine` that consumes immutable recorded observation events and produces a separate `BehavioralInferenceReport`.

The inference layer:

- never mutates raw observations;
- assigns deterministic identities to inferred events;
- preserves provenance to the exact durable observation-event IDs that support each inference;
- reports confidence explicitly;
- distinguishes current inferred operating state from observed facts;
- recognizes pump starts and only infers priming when an observed startup RPM peak later settles by a meaningful amount within a bounded startup window;
- records solar activation/deactivation context, including roof temperature, pool temperature, temperature differential, and pump RPM when available;
- summarizes repeated solar transitions using empirical medians and labels any hysteresis finding provisional rather than treating it as an IntelliCenter rule;
- fails non-authoritatively when evidence is missing or incomplete.

The Home Assistant coordinator refreshes behavioral inference only when 11.3B writes new durable evidence. Inference reads a bounded seven-day evidence window and runs in Home Assistant's executor, preserving event-loop responsiveness. Read-only Control Center sensors expose the current inferred operating state and solar-behavior assessment.

The HACS validation workflow is also promoted from manual-only execution to pull-request, `main` push, and manual execution. Repository visibility remains private during 11.3C/11.3D; public distribution remains a separate commissioning decision.

## Safety boundary

11.3C adds no Home Assistant service calls, control entities, command delivery, execution authority, or equipment actuation. Operating authority remains `NONE`, and PoolOS remains in OBSERVE/SHADOW mode.

## Consequences

11.3D can use the same provenance-aware inference output to calculate daily actual-operation metrics and compare them with PoolOS counterfactual recommendations. Live observation can later refine threshold estimates across repeated days without hard-coding assumptions derived from a single morning.

ADR-088 extends this same canonical inference authority with richer observed solar-transition context and deterministic open/closed solar episodes. It does not introduce a second solar inference engine or a control rule.
