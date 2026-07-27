# ADR-006: Model Shared-Equipment Modes as Hydraulic Routes

- Status: Accepted
- Date: 2026-07-27

## Context

Consumer interfaces use names such as **Pool**, **Spa**, **Spillway**, and
**Drain Hot Tub**. Those names are useful to people but do not precisely state
what the plumbing is doing. In a two-body shared-equipment system, the actual
control decision is the source body for suction and the destination body for
return water.

A body-centric translation operation can represent Pool and Spa but requires
special cases for Spillway and service draining. Special cases would couple the
vendor translator to consumer terminology and make future hydraulic layouts
harder to express.

## Decision

PoolOS will use `SetHydraulicRoute` as the canonical vendor-integration
operation. It specifies a suction body and a return body. Consumer-facing modes
are planner or UI aliases:

| Consumer-facing name | Suction | Return |
| --- | --- | --- |
| Pool | Pool | Pool |
| Spa | Spa | Spa |
| Spillway | Pool | Spa |
| Drain Hot Tub | Spa | Pool |

`ActivateBody` is not part of the vendor translator. A planner may later expose
it as a convenience intent and resolve it to a same-body hydraulic route.

Cross-body routes require both bodies to belong to the same configured
shared-equipment group. The translator emits a logical, transport-independent
Pentair command; valve sequencing, pump priming, flow verification, timeouts,
and protocol delivery remain responsibilities of later planning, protection,
and transport layers.

`Drain Hot Tub` is an administrative/service alias rather than an ordinary
consumer mode. A future planner or control-authority layer should require
explicit authorization, confirmation, and a bounded runtime before issuing the
underlying Spa-to-Pool route.

## Consequences

- All four shared-equipment routes use one internal representation.
- Spillway and spa draining do not require translator special cases.
- User-facing terminology remains available outside the translator.
- Safety policies can be applied to service aliases without contaminating the
  hydraulic model.
- Future bodies or destinations can extend the route model without adding a new
  mode abstraction.
