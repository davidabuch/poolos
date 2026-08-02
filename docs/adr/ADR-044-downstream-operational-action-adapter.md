# ADR-044: Downstream Operational Action Adapter Contract

## Status

Accepted and implemented for Epic 10.15H.

## Context

ADR-043 consolidated operational routing into one validated
`OperationalActionPipelineResult`. That result is the final command-free route
evidence before a downstream boundary, but PoolOS still needs an explicit
contract for consuming the evidence without coupling the core to Home
Assistant, Pentair, RS-485, or physical equipment.

Introducing an execution dispatcher as the first consumer would cross several
unreviewed safety boundaries at once. Reevaluation and operator review are
non-hardware concerns that can establish receipt, provenance, rejection, and
deferral semantics without authorizing delivery.

## Decision

PoolOS introduces a vendor-neutral `DownstreamOperationalActionAdapter`
contract. An adapter consumes exactly one immutable
`OperationalActionPipelineResult` and returns exactly one immutable
`DownstreamOperationalActionReceipt`.

The first implementation, `NonHardwareOperationalActionAdapter`, supports only:

| Pipeline target | Downstream outcome | Meaning |
|---|---|---|
| `NONE` | `NO_OP` | The validated action intentionally requires no work. |
| `REEVALUATION_SCHEDULER` | `DEFERRED` | Reevaluation evidence is preserved for a future scheduler. |
| `OPERATOR_REVIEW` | `ACCEPTED` | The blocked action is accepted for operator-review routing. |

Execution proposal and execution plan targets are rejected as unsupported by
this first adapter. The adapter does not invoke a scheduler or operator-review
service; it produces deterministic downstream evidence only.

## Validation and failure behavior

The adapter fails closed when:

- the pipeline result is rejected;
- the pipeline result does not carry the accepted route reason;
- accepted action identity is missing from acceptance evidence;
- the routed target differs from the canonical action target;
- a supported action, target, or boundary name is inconsistent;
- a reevaluation request lacks a non-empty reevaluation hint;
- the target belongs to execution proposal or execution plan handling.

Every attempt emits one of four explicit outcomes:

- `ACCEPTED`;
- `REJECTED`;
- `DEFERRED`;
- `NO_OP`.

## Identity and provenance

The receipt ID is deterministic. It is derived from canonical JSON containing
the adapter name, action ID, correlation identity, pipeline status and reason,
route target, boundary name, downstream outcome, and downstream reason. No
random UUID or wall-clock time participates in identity.

The receipt retains the complete immutable pipeline result and exposes the
canonical action, context, decision, plan, and correlation identities. Receipt
provenance merges immutable action and pipeline diagnostics with stable
downstream adapter evidence.

## Safety constraints

The downstream adapter boundary:

- accepts no raw observations, mutable runtime objects, vendor commands, or
  hardware endpoints;
- performs no planning, proposal generation, authorization, plan mutation, or
  execution;
- invokes no scheduler or operator-review implementation in Epic 10.15H;
- imports no Home Assistant, Pentair, RS-485, HAL, or delivery implementation;
- performs no network or device I/O;
- never actuates physical equipment.

Simulation-first and observation-first operation remain unchanged. Physical
control requires a separate ADR, an explicit runtime safety policy, reviewed
authorization and delivery contracts, and explicit approval.

## Future extension points

Future milestones may add reviewed adapters for:

- an immutable reevaluation scheduling request and dedicated scheduler;
- an operator-review queue or projection;
- execution proposal requests;
- execution plan retention, cancellation, or replacement requests.

Those adapters must consume validated pipeline results, preserve deterministic
receipt and provenance semantics, and remain separate from vendor delivery.
Any adapter that can ultimately reach execution must add explicit runtime-mode,
authorization, safety, simulator, and audit controls before physical delivery
is considered.

## Consequences

- The post-pipeline boundary is explicit and vendor-neutral.
- Invalid or unsupported routes fail closed with immutable evidence.
- No-op, deferral, rejection, and acceptance have stable semantics.
- The first adapter exercises useful operational routes without hardware risk.
- Actual scheduling, review publication, execution, and delivery remain future
  work.
