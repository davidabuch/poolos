# ADR-071: Recovery Coordinator

- **Status:** Accepted
- **Milestone:** 10.20A
- **Date:** 2026-08-05

## Context

PoolOS can now deliver a Home Assistant command, verify the resulting
observation, and produce an execution reconciliation recommendation. That
recommendation states what should happen next, but it does not determine whether
current recovery policy permits the corresponding follow-up.

Conflating reconciliation planning with recovery execution would allow a retry
recommendation to become a command or a reevaluation recommendation to become a
runtime submission without an explicit policy gate. Recovery authorization must
therefore remain separate from both evidence interpretation and action
execution.

## Decision

Add a pure `RecoveryCoordinator` that consumes one immutable
`ExecutionReconciliationResult` and one explicit immutable `RecoveryPolicy`.
The coordinator emits exactly one immutable directive:

- `NO_ACTION` for satisfied execution or when policy blocks all follow-up;
- `REQUEST_REEVALUATION` when reevaluation is recommended and permitted;
- `QUEUE_RETRY_REQUEST` when retry is recommended and permitted; or
- `REQUEST_OPERATOR_INTERVENTION` for operator-required or aborted execution,
  and as the fail-closed escalation when another recovery path is blocked.

Policy explicitly controls reevaluation requests, retry requests, and operator
intervention requests. Directive identity includes the reconciliation evidence,
policy identity, all policy permissions, decision time, disposition, and reason.
Receipt, verification, plan, step, correlation, policy, and caller provenance
are preserved.

The coordinator does not submit reevaluations, enqueue retries, notify an
operator, generate or deliver commands, advance a coordinator, mutate execution
state, poll, contact Home Assistant, or actuate equipment.

## Consequences

- Reconciliation recommendations cannot silently execute recovery.
- Retry remains opt-in and policy-controlled.
- Blocked recovery can escalate to operator review without inventing a second
  recovery mechanism.
- A policy may fail closed to `NO_ACTION` when every follow-up channel is
  explicitly prohibited.
- Recovery execution, queueing, notification, and reevaluation submission remain
  separate future milestones.
