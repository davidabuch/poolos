# PoolOS Constraint Engine

Milestone 9.3 introduces the safety and permission layer between control authority and execution.

## Architectural rule

Authority determines who may express intent. Constraints determine whether that intent may proceed safely. Constraints never call adapters and never execute hardware commands. Only `PoolRuntime` submits commands to the `ExecutionEngine`.

```text
Command
  -> Control Authority
  -> Constraint Engine
  -> Execution Engine
  -> Hardware Adapter
```

## Dispositions

Each constraint returns one structured decision:

- `ALLOW` — continue through the chain unchanged.
- `MODIFY` — replace the command with a safer equivalent and continue evaluating.
- `DENY` — permanently reject the command for the current evaluation.
- `DEFER` — do not execute yet; leave scheduled work eligible for a later cycle.
- `ESCALATE` — block execution and publish an event for operator or higher-level handling.

A modified command preserves the original `command_id`, allowing scheduler ownership, deduplication, execution records, and audit history to remain connected to the original intent.

## Deterministic ordering

Constraints are evaluated by descending numeric priority. Constraints with equal priority retain registration order. A terminal decision stops the chain immediately.

## Runtime behavior

For each runtime cycle:

1. Scheduler and policy commands are collected.
2. Control authority is resolved.
3. Only authorized commands enter the Constraint Engine.
4. Allowed or modified commands are submitted to execution.
5. Denied, deferred, or escalated commands are not submitted.
6. A scheduler step remains `ready` when one or more commands are temporarily blocked before submission.

## Audit and events

Every complete evaluation is retained in `ConstraintEngine.audit_log()` and added to `RuntimeCycle.constraint_evaluations`.

The engine publishes:

- `constraint.command.modified`
- `constraint.command.denied`
- `constraint.command.deferred`
- `constraint.command.escalated`

Event payloads include the command identity, target, reason, effective command when applicable, and structured details.

## Plugin example

```python
@dataclass
class GridOutageRpmConstraint:
    constraint_id: str = "grid_outage_rpm_cap"
    priority: int = 100

    def evaluate(self, command, context):
        if command.target == "pump.main.rpm" and command.value > 1800:
            replacement = ConstraintEngine.replace_command(command, value=1800)
            return ConstraintDecision.modify(
                self.constraint_id,
                command,
                replacement,
                context.evaluated_at,
                "pump RPM capped during grid outage",
            )
        return ConstraintDecision.allow(
            self.constraint_id,
            command,
            context.evaluated_at,
        )
```

Installation-specific freeze, heater-flow, dry-run, grid-loss, chemistry, and equipment-health constraints will be added as plugins without changing runtime execution semantics.
