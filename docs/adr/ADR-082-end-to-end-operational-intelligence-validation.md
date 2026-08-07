# ADR-082: End-to-End Operational Intelligence Validation

## Status
Accepted

## Decision
PoolOS will provide one deterministic, read-only composition boundary for the
11.2 operational-intelligence chain: canonical intents are arbitrated, selected
intents are pump-optimized, and the optimization result is converted into an
operator recommendation.

The composition result preserves the selected intent identities and explanations
at every layer. Its serialized evidence explicitly reports `authority: none` and
`command_delivery_enabled: false`.

This milestone does not connect the advisory chain to execution proposals,
execution plans, dispatch, vendor translation, Home Assistant services, or any
physical control path. Home Assistant continues to expose recommendations only as
read-only diagnostic evidence through the Control Center established in 11.2D.

## Rationale
A single vertical composition boundary allows commissioning to validate the
complete operational-intelligence path with real observations and simulations
without accidentally granting control authority. It also gives replay and shadow
analysis one stable result object whose provenance can be checked end to end.

## Consequences
- equivalent inputs and evaluation time produce equivalent advisory evidence;
- arbitration decisions constrain all downstream optimization and recommendation;
- infeasible optimization remains blocked rather than creating fallback control;
- no-action outcomes remain explicit;
- provenance and explanation continuity can be validated before live HA
  commissioning;
- physical actuation remains impossible through this API.
