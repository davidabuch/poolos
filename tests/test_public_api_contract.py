from __future__ import annotations

import poolos


STABLE_ROOT_API = (
    "BodyType",
    "CommandPriority",
    "EquipmentType",
    "HeatingSource",
    "PolicyPriority",
    "RecommendationSeverity",
)

COMPATIBILITY_ROOT_IMPORTS = (
    "PoolKernel",
    "PoolRuntime",
    "RuntimeContext",
    "PlanObjective",
    "PolicyEngine",
    "ExecutionPlan",
    "ExecutionCoordinator",
    "ClosedLoopSimulatorExecutionEngine",
)


def test_stable_root_api_is_explicit_and_unchanged() -> None:
    assert tuple(poolos.__all__) == STABLE_ROOT_API


def test_every_stable_root_symbol_exists() -> None:
    for name in STABLE_ROOT_API:
        assert hasattr(poolos, name), name


def test_wildcard_api_contains_only_declared_stable_symbols() -> None:
    namespace: dict[str, object] = {}
    exec("from poolos import *", namespace)

    exported = tuple(sorted(name for name in namespace if not name.startswith("__")))
    assert exported == tuple(sorted(STABLE_ROOT_API))


def test_representative_compatibility_imports_remain_available() -> None:
    for name in COMPATIBILITY_ROOT_IMPORTS:
        assert hasattr(poolos, name), name
        assert name not in poolos.__all__
