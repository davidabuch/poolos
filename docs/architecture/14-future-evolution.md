# Future Evolution

## Purpose

This chapter describes architectural direction, not committed product scope. It identifies how PoolOS can evolve without weakening its core contracts.

## Preserve the core before expanding it

Future work should preserve these invariants:

- canonical, vendor-independent domain models;
- deterministic evaluation;
- explicit time and identity;
- separation of reasoning, authority, execution, and delivery;
- simulation-first development;
- observable and replayable outcomes;
- fail-closed live actuation.

Growth is valuable only when these properties remain intact.

## Near-term architectural direction

### Complete deployment boundaries

The core already models decision, supervisory, disposition, execution, verification, recovery, and simulation capabilities. Future work may add production deployment boundaries for:

- Home Assistant lifecycle integration;
- observation ingestion and publication;
- persistence and restoration;
- scheduled and event-driven runtime invocation;
- commissioned vendor delivery;
- operational diagnostics.

These boundaries should remain thin and should call canonical PoolOS services rather than recreate domain logic in platform code.

### Strengthen subsystem facades

The repository currently contains many defining modules inside a largely flat package. Future review may introduce focused subsystem facades or subpackages when they improve navigation and contract clarity.

Any reorganization must preserve compatibility deliberately and should not precede a demonstrated need.

### Expand architectural contract tests

Current public API tests can be complemented by future tests for:

- forbidden dependency direction;
- identity stability;
- serialization compatibility;
- command-free supervisory boundaries;
- live-actuation commissioning gates;
- replay equivalence.

## Integration evolution

PoolOS should support additional controllers and platforms through adapters, not through vendor branches inside planning or decision logic.

A new adapter should provide:

- canonical observations;
- explicit connectivity and freshness evidence;
- canonical operation translation;
- delivery receipts;
- error classification;
- no independent policy authority.

Multiple transports may coexist only when source selection, command attribution, freshness, and conflict behavior are explicit.

## Operational evolution

Future production operation may include:

- persistent event and evidence stores;
- restart-safe queues;
- bounded scheduling and retry infrastructure;
- operator review workflows;
- richer health and readiness reporting;
- controlled live commissioning stages;
- migration and compatibility tooling.

Infrastructure should remain outside deterministic domain evaluation and should feed it through explicit requests.

## Broader domain reuse

Some PoolOS patterns may be useful in related systems such as IrrigationOS or future energy and landscape automation projects.

Potentially reusable concepts include:

- canonical observations;
- deterministic identity;
- policy and constraint evaluation;
- supervisory submission and coalescing;
- disposition routing;
- authorization and execution lifecycle;
- verification and recovery;
- flight records and replay.

Reuse should occur through extracted, proven contracts—not by prematurely forcing unrelated domains into one generic framework.

## What should remain PoolOS-specific

Pool chemistry, bodies of water, heating sources, circulation, filtration, sanitation, hydraulic constraints, equipment capabilities, and pool-specific policies should remain domain concepts.

A shared architecture does not require a shared domain model.

## Human control and explainability

Future automation should increase operator clarity rather than obscure control.

The system should continue to support:

- understandable explanations;
- visible ownership and authority;
- explicit degraded states;
- safe manual intervention;
- audit of what was decided and attempted;
- conservative behavior after uncertainty or restart.

## Machine learning and optimization

Forecasting or learned models may eventually improve estimates and ranking. They should enter as explicit evidence or evaluators with versioned provenance.

Learned output must not bypass:

- deterministic orchestration;
- safety constraints;
- authority checks;
- execution verification;
- human-readable explanations appropriate to the risk.

## Architecture versus roadmap

This chapter does not commit PoolOS to any named feature, release date, package move, adapter, or sibling product.

Committed sequencing belongs in `docs/ROADMAP.md`. Concrete architectural decisions belong in ADRs. This chapter describes only the direction in which compatible evolution is possible.

## Criteria for a new architectural layer

A new layer should be introduced only when:

- it owns a durable responsibility not represented elsewhere;
- its inputs and outputs can be defined clearly;
- it prevents coupling rather than adding ceremony;
- it has explicit non-responsibilities;
- an ADR explains why existing layers are insufficient.

## Architecture Manual maintenance

After Version 1.0, the manual should change when enduring architecture changes—not for every implementation milestone.

Routine feature history belongs in the roadmap, release notes, tests, and ADRs.

## Responsibilities

This chapter defines compatible directions for future growth and the invariants that expansion must preserve.

## Non-responsibilities

It is not a product roadmap, release plan, or promise to implement speculative systems.

## Future evolution

The preferred future is not the architecture with the most layers or abstractions. It is the smallest architecture that continues to make safe, explainable, replayable automation possible as scope grows.
