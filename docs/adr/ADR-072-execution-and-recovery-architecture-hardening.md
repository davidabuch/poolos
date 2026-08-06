# ADR-072: Execution and Recovery Architecture Hardening

- **Status:** Accepted
- **Milestone:** 10.20B
- **Date:** 2026-08-06

## Context

ADR-067 through ADR-071 established an end-to-end execution evidence path from
accepted operational action through Home Assistant delivery, delivery receipt,
post-delivery observation verification, reconciliation planning, and
policy-controlled recovery coordination.

Each boundary has focused tests, but the combined production-oriented path needs
permanent cross-boundary invariants before any subsystem is allowed to submit a
reevaluation, queue a retry, notify an operator, or influence live equipment.
The hardening work must increase confidence without adding another runtime layer
or changing production behavior.

## Decision

Add a dedicated architecture-hardening test suite that composes the existing
post-delivery verifier, reconciliation planner, and Recovery Coordinator as one
immutable evidence pipeline.

The scenarios permanently verify:

- verified delivery evidence resolves to satisfied and no action;
- timed-out evidence can become a policy-authorized retry request, but no retry
  is executed;
- policy-blocked retry recommendations escalate to operator review when allowed;
- persistent mismatches require operator intervention;
- changed assumptions take precedence and request supervisory reevaluation;
- failed delivery and contradictory receipt provenance fail closed;
- receipt, plan, step, correlation, operational-action, verification,
  reconciliation, and policy provenance remain continuous;
- exact replay produces equivalent results and stable identities;
- policy changes affect only the downstream recovery directive identity; and
- a fully restrictive recovery policy produces no hidden action.

No production model or boundary is duplicated. The milestone adds tests and
documentation only.

## Consequences

- The execution and recovery architecture gains permanent cross-boundary
  regression protection.
- Contradictory lifecycle evidence is proven to fail closed before any recovery
  action can be authorized.
- Retry recommendations remain advisory evidence rather than executed behavior.
- Future recovery-action milestones can build on explicit, tested invariants.
- No reevaluation submission, retry queue, operator notification, polling,
  Home Assistant communication, command delivery, or physical actuation is
  introduced.
