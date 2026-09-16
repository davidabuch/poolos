# ADR-110: Separate ownership origin, authority, health and command permission

## Status

Accepted behavioral design. Stage 1 is documentation and traceability only.
Implementation and physical commissioning remain separate approval stages.

## Context

The accepted owner-reviewed 90 scenarios require a complete autonomous day:
OFF -> acquisition -> filtration/Solar -> internal successor -> completion ->
Pool OFF/pump 0 -> another legitimate opportunity, without manual ownership repair.
The audit of v0.11.23 found that useful anti-adoption/currentness protections also
classify some unattributed contradictions as manual takeover, terminate aggregate
leases, and latch recovery. This conflates uncertainty about causation with evidence
of an operator. Selected-source and actual engagement semantics also differ from
the accepted contract. Passing the historical systemic guard proves its previous
doctrine, not the new scenarios.

## Decision

Incorporate all of [the accepted contract](../ownership/PoolOS_Ownership_Scenario_Contract.txt)
and [canonical ownership specification](../ownership/OWNERSHIP_ARCHITECTURE_SPEC.md).
AGENTS.md incorporates this behavioral authority. The imported source is unchanged;
its pre-incorporation precedence statement is historical. The architecture
specification interprets all scenarios together without rewriting their outcomes.
The [90-row traceability artifact](../ownership/scenario_traceability.json) tracks
gaps honestly and does not grant production compliance.

Use separate historical origin, concept-specific current authority, execution
health, and exact command permission. Positive operator evidence is required to
assign External/manual ownership. Unknown origin remains unknown. Expected native
convergence, unexplained drift, safety action, late old-generation consequences,
execution failure and legitimate purpose transitions have distinct meanings.
Unsafe commands still fail closed. A temporary permission denial need not erase
valid historical origin. Recovery is bounded and observable; no equality adoption,
unbounded retries or resurrection of stale executions.

BODY lifecycle is distinct from nested execution purposes. Explicit transfers,
prospective adoption, scoped manual hand-back, independent new opportunities and
Reset provide reviewed authority boundaries. Adoption is prospective and never
fabricates accepted command history. Reset creates a new generation and safely
reduces toward verified baseline under all normal safety gates.

## Explicit supersession map

The following decisions are superseded **only where stated**. Their historical
rationale and shipped implementation descriptions remain for review.

| Earlier document | Superseded behavior/interpretation | Preserved |
| --- | --- | --- |
| ADR-107, analog expectations and external/unattributed changes | A contradictory analog transition "remains external" must not mean an operator owns it. Failed correlation is ambiguity, not intent proof. | One bounded correlation registry, causal evidence, final lock, exact targets and global maintenance/controller deny. |
| ADR-107, native Solar Preferred conflict | Positively recognized ICP/OCP Solar Preferred becomes durable PoolOS policy intent; selected telemetry alone does not prove a gesture. | Distinction between native source and PoolOS policy; no arbitrary native writes or second configuration store. Current guard remains until reviewed implementation. |
| ADR-108, retention/preemption | Unattributed mismatch/unusable evidence cannot automatically establish External ownership or erase all domains. | Unsafe command denial, no retroactive attribution, exact concept receipts, generation and topology checks. |
| ADR-108, establishment/restart | Accepted commands are not the only legitimate prospective origin: explicit adoption is allowed. Unknown active equipment is not automatically operator-owned. | No reconstruction of old commands/receipts or ownership from equality. |
| ADR-108, purpose supersession | An obsolete execution remains terminal, but compatible body lifecycle need not end with it. | Immutable execution currentness, typed handoffs and exclusive circulation. |
| ADR-103, execution/cleanup and Hot Tub origin restrictions | Execution termination is not necessarily body-origin destruction; reviewed adoption may provide completion scope for an existing body. | Scoped live authorization, source/flow safety, post-command proof, no generic StopPump, body identity and no fabricated receipt. |
| ADR-103, source/RPM order and suppression | Solar operating RPM follows physical activity; positive Body OFF cancels its semantic opportunity, not future independent autonomy. | Real preparation/protection floors, v0.11.23 source-Off-before-circulation, no same-opportunity restart, strict verification. |
| ADR-109, takeover/failure/restart | Unexplained drift and control failure do not create External ownership; prospective adoption and domain-scoped overrides must support completion. | Sole filtration ledger, TOU deferral, typed thermal/filtration transfers, dynamic pump identity, one-epoch final gateway. |
| Pump-speed/session specification, session vocabulary | Pump-purpose transitions do not inherently end BODY lifecycle; manual hand-back requires attributable intent and verification. | Actual heat determines purpose, exact PMPCIRC, no startup RPM inference, safety floors and configurable baselines. |
| Pump-speed/session specification, outage section | Blanket permission for manual operation during the same active safety state is superseded by scenarios 79–80. | No command fighting after a completed one-time action where no mandatory constraint remains; reevaluate after safety clears. |
| ADR-004 and control-authority manual | Priority applies to explicit scoped intent, not observed mismatches; HA semantics follow the exposed control. | Safety priority, manual respect and reevaluation rather than snapshot restoration. |

No freshness window, tolerance, operation allowlist, commissioned body scope or
physical safety prerequisite is widened by this ADR. Future implementation must
review finite convergence budgets and evidence-origin capability, not assume
IntelliCenter exposes operator identity. Unknown values cannot verify commands.
Historical source-only/no-circulation residual disposal remains non-authorizing;
capture waiting must retain its exact token until transfer, verification or typed
invalidation, never silently consume an attempted transfer.

## Consequences and rejected alternatives

- Keep existing modules and one final command gateway; extend canonical models
  rather than build an independent ownership/recovery controller.
- Split tests using the same physical stimulus with and without positive intent.
  Preserve their useful chronology, no-adoption and safety assertions.
- Existing labels/diagnostics and durable intent schemas need explicit migration;
  never migrate legacy "external" flags into proven operator intent.
- Rejected: always letting PoolOS win; equality-based reacquisition; permanently
  yielding on every mismatch; renaming Solar operating RPM as a protection floor;
  Reset as a substitute for ordinary recovery; skipping verification to regain
  liveness; resetting correction budgets on reevaluation.
- Implementation plan and outstanding engineering parameters live in
  [STAGE_1_TRACEABILITY.md](../ownership/STAGE_1_TRACEABILITY.md). No physical
  commissioning result is claimed by this documentation change.
