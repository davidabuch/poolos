# Canonical Identity Model

> **Architecture Manual v1.0** · Chapter 8 of 15

## Purpose

PoolOS uses deterministic identity to make evidence traceable, replayable, and comparable across subsystem boundaries. Identity answers: "Is this logically the same thing?" It is distinct from display names, database row numbers, object memory addresses, and timestamps added only for audit.

## Identity principles

1. **Canonical before vendor-specific.** Core identity represents the PoolOS concept, not the external entity name.
2. **Deterministic where evidence is deterministic.** Equivalent normalized inputs produce the same logical identifier.
3. **Immutable after creation.** An identifier does not change because later state changes.
4. **Scoped by meaning.** Observation, context, decision, plan, and execution identities are not interchangeable.
5. **Traceable across boundaries.** Downstream evidence carries upstream identifiers in provenance.
6. **Time is included only when semantically necessary.** Audit time alone should not redefine logical identity.

## Identity chain

```text
Canonical installation, body, equipment, resource, and capability IDs
                              |
                              v
                  Observation identities
                              |
                              v
                 Runtime submission IDs
                              |
                              v
                 Coalescing batch ID
                              |
                              v
              Decision evaluation context ID
                              |
                              v
          Supervisory evaluation assembly ID
                              |
                              v
             Supervisory invocation ID
                              |
                              v
                    Decision ID
                              |
                              v
             Operational disposition ID
                              |
                              v
          Supervisory evaluation runtime ID
                              |
                              v
       Execution proposal, authorization, and plan IDs
                              |
                              v
        Execution session, step, receipt, and record IDs
```

Not every cycle produces every identity. A blocked context, retained decision, or no-action disposition may stop before execution.

## Stable domain identity

Long-lived physical and logical subjects use stable canonical IDs:

- installation;
- pool or spa body;
- equipment;
- resource;
- capability;
- policy;
- goal or objective;
- planning strategy.

These identifiers should not depend on a Home Assistant entity ID or a Pentair label. Adapters maintain the mapping between canonical identity and external identity.

## Observation identity

An observation identifies a claim about a canonical subject at a defined time and from a defined source. Depending on the observation contract, identity may include:

- subject identity;
- feature or measured property;
- observed value;
- source;
- observation time;
- quality or truth classification.

Two adapters reporting the same value are not automatically the same observation because provenance may differ.

## Runtime submission and trigger identity

A runtime submission represents one accepted request for supervisory evaluation. Coalescing groups equivalent or overlapping submissions into one batch while preserving all consumed submission IDs.

The batch identity is evidence that a particular normalized trigger set was considered together. Coalescing must not destroy individual trigger provenance.

## Evaluation context identity

The evaluation context identifies one immutable decision snapshot. Current assembly derives it from normalized evidence such as:

- coalescing batch identity;
- consumed submissions;
- evaluation time;
- runtime mode;
- goals;
- observation and forecast evidence;
- policies;
- freshness;
- blockers;
- prior-decision identity;
- planning objective;
- trigger evidence.

Equivalent normalized input evidence produces the same context identity. Order-insensitive collections are normalized before hashing.

## Assembly identity

The supervisory assembly identity proves which coalescing batch, context, planning objective, and prior-decision evidence were combined into the existing orchestration request.

Assembly does not identify a decision. It identifies the reviewed input boundary that made decision invocation possible.

## Invocation identity

The invocation identity identifies the logical act of invoking the existing decision orchestrator for one assembled request. Wall-clock invocation time is retained as audit evidence but does not need to redefine the logical invocation when the same assembly is replayed.

## Decision identity

A decision identity belongs to the selected, retained, deferred, or blocked cognitive outcome according to the decision model that created it. It must remain distinct from:

- the context that was evaluated;
- the plan alternative that was considered;
- the execution plan that may later implement it.

This distinction allows multiple evaluations of related context and multiple execution attempts to remain auditable.

## Operational disposition identity

Operational disposition identifies the plan-management interpretation of a decision in relation to current execution state. The same decision may require a different disposition when the current plan summary differs.

For example, an accepted decision may mean "submit" when no plan exists and "retain" when the matching plan is already active.

## Supervisory runtime identity

The supervisory runtime identity ties together the reviewed composition evidence for one complete evaluation cycle. It is derived from stable upstream and disposition identities rather than randomness.

It does not imply that execution occurred.

## Execution identities

Execution uses several scopes because authorization, planning, delivery, and verification are separate facts:

- **Proposal ID:** candidate execution intent derived from accepted upstream evidence.
- **Authorization ID:** the authority and runtime-mode decision for that proposal.
- **Execution plan ID:** immutable ordered work specification.
- **Execution/session ID:** one lifecycle instance attempting the plan.
- **Step ID:** one canonical unit of work within the plan.
- **Delivery receipt ID:** adapter evidence for one delivery attempt.
- **Verification ID:** comparison of expected and observed outcome.
- **Recovery ID:** classification and recommendation following interruption or fault.
- **Flight-record ID:** ordered audit evidence.

A retry or restarted session should not silently overwrite the identity of the original attempt.

## Canonicalization

Deterministic IDs require canonical input representation. Current patterns include:

- sorted mapping keys;
- normalized enum values;
- timezone-aware ISO timestamps;
- sorted order-insensitive tuples;
- explicit rejection of unsupported identity values;
- compact canonical JSON;
- namespaced hash prefixes.

A prefix communicates identity type, while the digest represents normalized evidence.

## Identity versus provenance

Identity states what the object logically is. Provenance explains how it was produced.

A result should often carry both:

```text
identity:
  supervisory-evaluation-runtime-...

provenance:
  coalescing_batch_id: ...
  context_id: ...
  assembly_id: ...
  invocation_id: ...
  decision_id: ...
  disposition_id: ...
```

Provenance should be additive and immutable. It should not require parsing a compound ID to recover the evidence chain.

## Identity versus time

A timestamp belongs in identity when it changes the represented fact, such as an observation at a particular instant or an evaluation snapshot at a defined time.

A timestamp should remain audit-only when it merely records when an otherwise identical operation happened. This distinction supports deterministic replay while retaining operational history.

## Identity versus external names

Home Assistant entity IDs, device IDs, Pentair circuit names, and vendor object IDs are adapter mappings. They may change without changing the canonical PoolOS subject.

```text
Canonical equipment ID
        <-> adapter mapping
        <-> Home Assistant entity or vendor object
```

Core policy and decision logic should use canonical identity.

## Validation rules

Identity-bearing models should validate:

- non-empty identifiers;
- expected namespace or type where required;
- consistency between direct fields and provenance;
- uniqueness in collections that require it;
- timezone awareness for identity timestamps;
- stable ordering before derivation;
- matching upstream identities across composed boundaries.

## Common identity errors

- using a mutable display name as a primary ID;
- including dictionary insertion order in a hash;
- including a replay timestamp in logical identity;
- treating a decision ID as an execution-plan ID;
- losing consumed trigger IDs during coalescing;
- allowing an adapter entity ID to become the domain identity;
- overwriting an original execution attempt during retry.

## Responsibilities

This chapter defines the identity scopes and derivation principles used across PoolOS.

## Non-responsibilities

It does not freeze every current prefix or require all legacy models to be refactored immediately.

## Future evolution

A later identity inventory may document every concrete prefix and add repository-wide consistency tests once naming review is complete.

---

[Previous: Data Flow](06-data-flow.md) · [Architecture Manual Index](../ARCHITECTURE.md) · [Next: Safety Model](08-safety-model.md)
