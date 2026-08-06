# ADR-077: PoolOS Control Center

- **Status:** Accepted
- **Milestone:** 11.1E
- **Date:** 2026-08-05

## Context

The read-only Home Assistant observation bridge and shadow runtime now produce canonical health, evaluation, plan, objective, and explanation evidence. That evidence is available through diagnostics but is not visible as ordinary Home Assistant state, making commissioning difficult for an operator.

## Decision

Add a read-only Home Assistant `sensor` platform that publishes eight diagnostic entities for operating mode, commissioning stage, observation health, shadow status, last evaluation, last shadow plan, current objective, and the latest shadow explanation.

All entities belong to one PoolOS Control Center diagnostic device. Their state and attributes are derived exclusively from the existing coordinator, observation snapshot, and shadow runtime. They expose identities, counts, health, and explanations while avoiding raw mapped observation values.

Provide a repository dashboard definition at `dashboards/poolos_control_center.yaml`. It presents authority and safety, observation health, shadow runtime status, and explanation evidence. Dashboard installation remains an explicit operator action; PoolOS does not mutate Home Assistant dashboard configuration automatically.

## Safety constraints

- The external operating mode remains `OBSERVE`.
- Every entity is diagnostic and read-only.
- No switch, button, select, number, climate, or service is added.
- No Home Assistant service call is made.
- No execution proposal, authorization, dispatch, recovery, or command delivery occurs.
- Shadow evidence must never be represented as an executed action.
- Authority increases remain subject to explicit operator approval under ADR-073.

## Consequences

- Operators can commission PoolOS through normal Home Assistant entities.
- Dashboard cards update through the existing coordinator lifecycle.
- Entity history can support later commissioning review.
- Future operator experiences may reuse the device and entities without changing the core shadow runtime.
