# ADR-076: Home Assistant Read-Only Shadow Runtime

- **Status:** Accepted
- **Milestone:** 11.1D
- **Date:** 2026-08-05

## Context

ADR-075 connects PoolOS to configurable Home Assistant entity mappings and
produces canonical read-only observation snapshots. PoolOS must next prove that
its existing supervisory decision architecture can run continuously against
live observations without gaining command authority or presenting operational
recommendations as approved actions.

The current planner requires an explicit objective. Commissioning does not yet
have user goals, schedules, or authority settings. Inventing an operational goal
would create misleading recommendations.

## Decision

Add a read-only shadow runtime with two layers:

1. a Home Assistant adapter that extracts normalized facts from each canonical
   observation snapshot; and
2. a platform-neutral `ShadowRuntime` that invokes the existing
   `DecisionOrchestrator` in `SHADOW` mode.

During 11.1D, the runtime uses a commissioning baseline objective whose target
is the currently observed pool temperature. This deliberately produces a
completed or blocked plan with no proposed commands. It proves observation,
context construction, planning, explanation, stability, and decision recording
without pretending that PoolOS has an operator-approved objective.

Each evaluation receives a deterministic observation fingerprint and emits a
stable evaluation identity. The existing planner may retain its own plan
identity semantics. Diagnostics expose identities, status, counts, and blockers
but omit raw observed values and rendered explanations.

The external commissioning mode remains `OBSERVE`. Internal use of the
orchestrator's `SHADOW` runtime mode does not grant authority.

## Safety boundaries

The shadow runtime:

- does not invoke execution proposal construction;
- does not authorize, schedule, dispatch, translate, or deliver commands;
- does not call Home Assistant services;
- does not register entity-control platforms;
- does not submit retries, reevaluations, or recovery actions;
- does not advance the external operating mode;
- does not actuate physical equipment.

Unhealthy observation snapshots block planning rather than being silently
accepted.

## Consequences

- PoolOS can continuously exercise its real decision architecture against live
  Home Assistant observations.
- Operators gain diagnostic evidence that the runtime is evaluating without
  granting it authority.
- Later milestones can add operator-facing shadow dashboards and explicit goals
  without replacing this boundary.
- The baseline objective must not be interpreted as an optimization or control
  recommendation.
