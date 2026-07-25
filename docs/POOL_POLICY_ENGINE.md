# PoolOS Policy Engine

The policy subsystem is the decision layer between normalized kernel state and
immutable commands. Policies inspect `PoolKernel`, explain their reasoning, and
propose commands. They never execute commands or import a hardware adapter.

## Core behavior

- Policies are registered and independently enabled or disabled.
- Each policy returns an immutable `PolicyOutcome` containing commands and rationale.
- The engine resolves competing commands for the same logical target.
- Higher `PolicyPriority` wins; registration order deterministically breaks ties.
- Suppressed commands remain visible in `PolicyEvaluation` for diagnostics.
- The resulting commands must still pass through `ExecutionEngine`.

## Opinionated defaults

`build_default_policy_engine()` installs configurable defaults:

1. **Circulation safety** — starts circulation if heating is active without flow.
2. **Sanitizer interlock** — stops sanitization if circulation is not running.
3. **Heating demand** — starts or stops available heating equipment using a deadband.

Defaults can be omitted individually, and policies can be disabled at runtime.
This makes PoolOS opinionated but configurable rather than hard-coded.

## Deliberate scope

This milestone does not submit commands, schedule work, select vendor-specific
modes, or manipulate Home Assistant entities. Those responsibilities remain in
the execution, scheduling, planning, and adapter layers.
