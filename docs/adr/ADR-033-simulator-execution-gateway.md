# ADR-033: Simulator Execution Gateway

- **Status:** Accepted
- **Date:** 2026-07-31
- **Decision owners:** PoolOS project

## Context

PoolOS already has a generic `VendorCommandGateway`, a validated runtime
composition boundary, and a `SimulatorVendorCommandEndpoint`. The supervisory
execution framework completed in Epic 10.13 still has no delivery integration.
The first delivery-facing milestone must admit only simulator endpoints and
must not duplicate translation, routing, receipt, or runtime-safety concepts.

## Decision

PoolOS will introduce `SimulatorExecutionGateway` as a narrow composition
boundary. It is constructed only from a validated `PoolRuntimeEnvironment` in
`RuntimeMode.SIMULATION` with physical delivery prohibited and one or more
endpoints classified as `DeliveryEndpointKind.SIMULATOR`.

The gateway:

- reuses `PoolRuntimeEnvironment.build_endpoint_registry()`;
- delegates actual endpoint resolution and invocation to
  `VendorCommandGateway`;
- delivers one already-translated `VendorCommand` exactly once;
- preserves the existing `DeliveryReceipt` contract;
- supports explicit endpoint selection;
- permits automatic vendor routing only when it is unambiguous.

It does not translate `PoolOperation` objects, consume execution plans,
coordinate steps, advance lifecycle state, verify observations, or perform
restart recovery.

## Safety consequences

- Shadow and live runtime environments are rejected.
- Physical delivery cannot be enabled through this gateway.
- Non-simulator endpoints are rejected before delivery.
- Multiple endpoints for the same vendor require explicit endpoint selection.
- Home Assistant and physical Pentair delivery remain out of scope.

## Alternatives considered

### Rebuild the generic vendor-command gateway

Rejected because the existing gateway already owns routing, vendor validation,
and single endpoint invocation.

### Connect the execution coordinator directly to simulator endpoints

Rejected because it would couple lifecycle orchestration to transport and
routing details before the execution-step integration contract is defined.

### Combine simulator gateway, execution integration, and receipts

Deferred. Those concerns can be combined later only if implementation proves
they remain independently reviewable. Epic 10.14A establishes the safety
composition boundary first.

## Follow-up

Epic 10.14B may adapt one authorized execution step to this gateway. It must
reuse this boundary and may not bypass the runtime environment or generic
vendor-command gateway.
