# ADR-073: Operational Commissioning Philosophy

- **Status:** Accepted
- **Milestone:** 11.1A
- **Date:** 2026-08-06

## Context

PoolOS now has a deterministic execution and recovery architecture capable of
planning, authorizing, delivering, verifying, reconciling, and coordinating
recovery evidence. That technical capability does not by itself justify control
of real equipment.

Operational authority must be earned through observed evidence, transparent
recommendations, explicit operator consent, and reversible commissioning. The
commissioning model must apply beyond Home Assistant so that PoolOS can retain
the same safety and trust principles with future runtime or vendor adapters.

## Decision

Adopt an operational commissioning philosophy in which PoolOS advances through
six explicit authority modes:

```text
OBSERVE -> LEARN -> ADVISE -> SHADOW -> ASSIST -> CONTROL
```

Each mode defines permitted behavior, prohibited behavior, readiness criteria,
and rollback requirements. Technical readiness makes a higher mode eligible;
it never activates that mode automatically. Every increase in authority requires
explicit operator approval.

PoolOS commissioning is governed by these principles:

1. **Evidence before action.** Decisions and actions require inspectable evidence.
2. **Observation before authority.** PoolOS must observe and understand the real
   system before it may influence it.
3. **Trust is earned continuously.** Past success does not permanently justify
   present authority.
4. **Every recommendation and action is explainable.** Operators must be able to
   inspect the reason, inputs, policy, expected outcome, and evidence chain.
5. **Humans remain in charge.** Manual intervention and explicit operator intent
   take precedence within the safety model.
6. **Authority never increases automatically.** Advancement requires operator
   approval even after all technical criteria are satisfied.
7. **Rollback is immediate and simple.** An operator must be able to return to
   `OBSERVE` without reconstructing hidden state or editing code.
8. **Failure reduces authority.** Missing, stale, contradictory, or unhealthy
   evidence blocks advancement and may force a lower mode.
9. **Learning is deterministic and inspectable.** PoolOS learns measurable
   physical characteristics, not opaque or unreviewable behavior.
10. **Delivery is not proof of physical success.** Observed state verification
    remains required after command delivery.
11. **No hidden ownership.** PoolOS authority, ownership, arming state, and mode
    must be visible to the operator.
12. **Commissioning is incremental.** Control expands by bounded capability, not
    by a single system-wide switch.

## Operating Modes

### OBSERVE

PoolOS may ingest, normalize, validate, publish, and record observations. It may
not make operational recommendations or send commands.

### LEARN

PoolOS may derive deterministic physical and operational characteristics from
recorded evidence. Learned values must include source evidence, confidence,
freshness, and reproducible derivation. It may not recommend or command.

### ADVISE

PoolOS may produce human-readable recommendations and alternatives with reasons,
expected outcomes, assumptions, and uncertainty. It may not construct an
actuation-ready command path or send commands.

### SHADOW

PoolOS may run the complete decision and execution-planning path, including
expected observations and recovery planning, while command delivery remains
blocked. Shadow output must be clearly labeled as hypothetical.

### ASSIST

PoolOS may execute only explicitly approved, bounded, low-risk capabilities.
Each assisted capability must have its own eligibility, arming, verification,
rollback, and ownership rules. Unapproved capabilities remain in shadow mode.

### CONTROL

PoolOS may exercise configured operational authority within explicit safety,
ownership, and policy limits. Control remains revocable, observable, verified,
and subordinate to operator intervention and safety constraints.

## Advancement and Regression

Advancement requires all defined technical criteria plus explicit operator
approval. PoolOS must display why a mode is eligible and which criteria remain
unmet. Approval must identify the target mode and, for `ASSIST` or `CONTROL`,
the capabilities being authorized.

PoolOS may automatically reduce authority when required by safety, health, or
evidence failures. It may never automatically increase authority. Recovery from
a forced regression requires restored health evidence and new operator approval.

## Consequences

- Commissioning becomes a first-class architecture concern rather than a
  deployment checklist.
- Home Assistant integration work must default to read-only behavior.
- Future learning, advisory, shadow, and control capabilities must declare the
  minimum mode they require.
- Operating mode, capability authorization, and rollback state must be visible
  and auditable.
- Live control cannot be enabled merely because transport credentials exist.
- Subsequent commissioning milestones must trace their behavior to this ADR.
