# PoolOS Public API Policy

## Purpose

PoolOS currently exposes two different root-package surfaces:

1. a small, explicitly declared stable wildcard API in `poolos.__all__`; and
2. a much larger direct-import compatibility surface created by historical re-exports in
   `poolos/__init__.py`.

This document makes that distinction explicit before any exports are removed, renamed, or moved.

## Stable root API

The following names are the only symbols currently declared stable for wildcard import from
`poolos`:

- `BodyType`
- `CommandPriority`
- `EquipmentType`
- `HeatingSource`
- `PolicyPriority`
- `RecommendationSeverity`

These names are listed in `poolos.__all__` and form the intentionally small stable root API.

## Compatibility root API

Many additional names remain directly importable from `poolos`, including domain models, the
original runtime and execution framework, planning and policy types, simulation types, execution
lifecycle types, and simulator-only execution components.

Examples include:

- `PoolKernel`
- `PoolRuntime`
- `RuntimeContext`
- `PlanObjective`
- `PolicyEngine`
- `ExecutionPlan`
- `ExecutionCoordinator`
- `ClosedLoopSimulatorExecutionEngine`

These imports remain supported for repository compatibility during the architecture review, but
are not yet declared part of the long-term stable root API.

## Internal and subsystem APIs

New supervisory, operational, execution, simulation, Home Assistant, and vendor-specific code
should prefer imports from the defining module rather than adding more root-package re-exports.

Examples:

```python
from poolos.supervisory_evaluation_runtime import SupervisoryEvaluationRuntime
from poolos.operational_disposition import OperationalDispositionEngine
from poolos.execution_coordinator import ExecutionCoordinator
```

This keeps subsystem ownership visible and prevents `poolos/__init__.py` from becoming the default
entry point for every implementation type.

## Compatibility rules during architecture cleanup

Until a dedicated deprecation milestone is approved:

- do not remove existing root-package direct imports;
- do not rename compatibility exports;
- do not silently expand `poolos.__all__`;
- do not add new root re-exports without an explicit public-API decision;
- prefer defining-module imports in new production code and tests;
- treat changes to `poolos.__all__` as public-contract changes.

## Future review

A later architecture milestone will classify every compatibility export as one of:

- stable public API;
- subsystem public API;
- compatibility-only export;
- deprecated export;
- internal implementation detail.

That milestone may introduce focused subsystem facades, but no package moves or compatibility
removals are authorized by this policy alone.
