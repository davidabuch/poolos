# ADR-070: Execution Reconciliation and Recovery Planning

- **Status:** Accepted
- **Milestone:** 10.19C
- **Date:** 2026-08-05

## Context

PoolOS can deliver a Home Assistant command, normalize delivery evidence, create
an execution receipt, and verify the resulting Home Assistant observation. The
remaining gap is deciding what the supervisory system should recommend after
verification succeeds, remains unresolved, or fails.

The existing repository already contains a desired-versus-actual reconciliation
engine for the older runtime and restart-recovery assessment for persisted
execution state. Reusing either as the new post-delivery policy boundary would
mix responsibilities and could cause hidden retries or state mutation.

Verification evidence alone also cannot prove that the assumptions supporting
the original command remain current, that retry policy permits another attempt,
or that a mismatch is persistent. Those safety-relevant facts must be supplied
explicitly by the caller.

## Decision

Add a pure `ExecutionReconciliationPlanner` that consumes one immutable
`PostDeliveryVerificationResult` together with explicit caller-provided facts:

- whether execution assumptions remain current;
- whether retry is permitted by policy; and
- whether an observed mismatch is persistent.

The planner emits exactly one immutable recommendation:

- `SATISFIED` when the expected state is verified;
- `REEVALUATE` when assumptions changed, evidence remains pending, or a new
  nonpersistent mismatch requires fresh supervisory reasoning;
- `RETRY_RECOMMENDED` when stale or timed-out evidence exists and retry is
  explicitly permitted;
- `OPERATOR_INTERVENTION_REQUIRED` for persistent mismatch, unavailable
  observation, or expired evidence when retry is prohibited; or
- `ABORT` when verification evidence was rejected or unsupported.

The recommendation preserves receipt, plan, step, verification, correlation,
and policy provenance. Deterministic identity includes all facts that affect the
result.

The planner does not generate or deliver a command, invoke a retry, submit a
reevaluation, advance a coordinator, mutate execution state, poll observations,
contact Home Assistant, or actuate equipment.

## Consequences

- PoolOS gains an explicit policy boundary between verification evidence and
  future recovery execution.
- A retry recommendation cannot silently become a retry.
- Changed assumptions take precedence over retry recommendations and force a
  fresh supervisory evaluation.
- Persistent mismatch and retry permission remain explicit upstream facts
  rather than unsafe inference.
- Automatic retry, bounded recovery execution, and reevaluation submission
  remain separate future milestones.
