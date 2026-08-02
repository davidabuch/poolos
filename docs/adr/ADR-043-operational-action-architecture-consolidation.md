# ADR-043: Operational Action Architecture Consolidation

## Status

Accepted.

## Context

ADR-040 introduced the canonical operational action pipeline. ADR-041 made the
operational action registry the declarative route authority. ADR-042 then added
an operational action exchange that accepted an already validated pipeline
result, repeated the registry lookup, revalidated the same target evidence, and
returned another immutable routing result.

The pipeline and exchange therefore owned overlapping responsibilities:

- route resolution through the same registry;
- unsupported-route rejection;
- target-consistency validation;
- immutable routing diagnostics.

Keeping both layers would add an additional request/result model and a second
registry lookup without establishing a meaningfully different architectural
boundary.

## Decision

Remove `OperationalActionExchange` as a runtime abstraction and consolidate its
useful route evidence into `OperationalActionPipelineResult`.

The operational action pipeline now:

- validates one canonical action;
- suppresses duplicate action identities;
- resolves the route exactly once through `OperationalActionRegistry`;
- verifies the canonical action target against the registration;
- includes both `routed_target` and the registry's canonical `boundary_name` in
  an accepted immutable result;
- preserves registry, route, and pipeline diagnostics;
- rejects unsupported or inconsistent actions without exposing a destination.

An accepted pipeline result must identify a non-empty boundary name. A rejected
pipeline result must identify neither a routed target nor a boundary name.

ADR-042 remains in the repository as architectural history but is superseded by
this decision.

## Consequences

- Route resolution occurs once rather than twice.
- `OperationalActionPipelineResult` is the final command-free routing evidence
  before future side-effecting adapters.
- The operational decision chain loses one module, one request/result family,
  and duplicate route-consistency logic.
- Registry declarations remain data-only and no downstream boundary is invoked.
- Determinism, immutable diagnostics, duplicate suppression, replayability, and
  simulator-only safety are preserved.

## Finalized Flow

```text
OperationalDisposition
        |
        v
OperationalContext
        |
        v
OperationalDispositionOrchestrator
        |
        v
CanonicalOperationalAction
        |
        v
OperationalActionPipeline <-> OperationalActionRegistry
        |
        v
Validated OperationalActionPipelineResult
============================================
Future side-effect boundary
```

## Rejected Alternatives

### Keep the exchange as an additional safety layer

Rejected because it rechecked evidence already guaranteed by the immutable
pipeline result and registry lookup without introducing an independent source
of truth.

### Move routing entirely into the registry

Rejected because the registry should remain declarative data and deterministic
lookup only. Duplicate suppression and canonical action validation remain
pipeline responsibilities.

### Integrate a downstream adapter in the same milestone

Rejected to keep consolidation behavior-preserving and simulator-only. Future
side-effect contracts should be designed separately against the simplified
boundary.
