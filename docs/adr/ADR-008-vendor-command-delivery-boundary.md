# ADR-008: Deliver Vendor Commands Through a Dedicated Gateway and Endpoint Port

- **Status:** Accepted
- **Date:** 2026-07-27
- **Decision owners:** PoolOS architecture
- **Supersedes:** None
- **Related:** ADR-003, ADR-007

## Context

ADR-007 established `PoolOperation` as the canonical planner-to-hardware work
contract and assigned deterministic vendor translation to the integration layer.
Milestones 10.4B.1 through 10.4B.3A now provide these boundaries:

```text
PoolOperation
    -> WorkDispatcher
        -> OperationTranslationHandler
            -> TranslatorRegistry
                -> TranslationResult
                    -> VendorCommand
```

`VendorCommand` is deliberately transport-neutral. It describes vendor
semantics (`vendor`, `operation`, `target`, parameters, and metadata), but it
does not know which controller connection should receive the command or how the
command should be serialized and delivered.

The current HAL provides a different set of contracts:

```text
HardwareAdapter
    -> lifecycle, discovery, health

HardwareEquipment
    -> observations and stable equipment capabilities

Transport
    -> connect, disconnect, send, read
```

The HAL also defines `CommandReceipt`, but `HardwareAdapter` has no command
submission method. Adding `deliver(VendorCommand)` directly to
`HardwareAdapter` would make the HAL import the integration layer and would
combine discovery/lifecycle responsibilities with command delivery. Sending a
`VendorCommand` directly through `Transport.send()` would instead force the
runtime or translator to choose destinations, serialize payloads, interpret
responses, and know protocol details.

A separate boundary is therefore required between logical vendor commands and
transport delivery.

## Decision

### 1. Introduce a dedicated vendor-command delivery layer

PoolOS will add a narrow delivery package whose central component is:

```text
VendorCommandGateway
```

The gateway sits between pure translation and vendor/transport implementation:

```text
PoolOperation
    -> OperationTranslationHandler
        -> TranslationResult
            -> VendorCommandGateway
                    -> VendorCommandEndpoint
                        -> Transport
                            -> Hardware
```

The delivery layer is an intentional composition boundary. It may depend on the
integration command model and the generic HAL receipt/transport contracts. Core
planning, policy, authority, scheduling, and translation code must not depend
on concrete transports or vendor endpoint implementations.

### 2. Keep `VendorCommand` free of runtime routing concerns

`VendorCommand` remains a deterministic description of vendor semantics. It
will not gain connection objects, transport instances, Home Assistant entity
IDs, URLs, serial ports, credentials, retry state, or controller sessions.

Runtime routing is supplied explicitly to the gateway alongside the command:

```text
VendorCommandGateway.deliver(
    endpoint_id,
    command,
    correlation_id,
    timeout (optional),
)
```

A separate `DeliveryRequest` wrapper is intentionally deferred because the
current inputs do not require independent request behavior or lifecycle. This
avoids a pass-through abstraction while keeping routing typed and explicit.
`endpoint_id` identifies one configured writable controller endpoint. It is
separate from:

- `VendorCommand.vendor`, which identifies the vendor dialect;
- `VendorCommand.target`, which identifies the vendor object or logical target;
- a transport destination, which is an endpoint implementation detail.

This distinction is required because one PoolOS installation may eventually
contain multiple controllers from the same vendor.

### 3. Route through a registered endpoint port

The delivery layer will define a structural endpoint contract similar to:

```python
class VendorCommandEndpoint(Protocol):
    @property
    def endpoint_id(self) -> str: ...

    @property
    def vendor(self) -> str: ...

    def deliver(
        self,
        command: VendorCommand,
        *,
        correlation_id: str,
        timeout: float | None = None,
    ) -> CommandReceipt: ...
```

The exact Python spelling may evolve during implementation, but the ownership
rules are fixed:

- the gateway resolves `endpoint_id`;
- the gateway verifies that endpoint vendor and command vendor match;
- the endpoint serializes the vendor command into protocol payloads;
- the endpoint chooses transport destinations;
- the endpoint invokes the transport;
- the endpoint maps transport responses and exceptions into `CommandReceipt`;
- the endpoint contains no planning, policy, scheduling, authority, or
  reconciliation logic.

Endpoint implementations belong with vendor composition code, not in the core
planner or pure integration translator.

### 4. Preserve the existing HAL responsibilities

`HardwareAdapter` will not be expanded merely to accept `VendorCommand`.
Its existing lifecycle, discovery, and health responsibilities remain valid.

A concrete vendor integration may use one object that satisfies both
`HardwareAdapter` and `VendorCommandEndpoint`, but the two interfaces remain
separate. This permits:

- read-only adapters;
- write-only test endpoints;
- one adapter exposing several controller endpoints;
- endpoint replacement without redefining equipment discovery;
- transport simulation without constructing physical equipment objects.

`Transport` remains semantics-free. It only moves a payload to a destination
and returns a transport response.

### 5. The gateway owns routing and admission, not protocol behavior

`VendorCommandGateway` owns:

- endpoint registration and lookup;
- duplicate endpoint protection;
- endpoint/vendor compatibility validation;
- correlation propagation;
- invocation of the selected endpoint;
- consistent conversion of routing failures into delivery failures;
- optional delivery-level audit hooks.

It does not own:

- operation translation;
- protocol serialization;
- transport retry loops;
- physical-state verification;
- policy or authority;
- command deduplication;
- sequencing decisions derived from pool safety semantics.

### 6. Translation and delivery remain separate phases

`OperationTranslationHandler` remains pure and deterministic. It continues to
return `TranslationResult` without performing I/O.

A later orchestration component will compose translation and delivery. Its
working name is:

```text
OperationExecutionHandler
```

Its role will be limited to:

1. resolve translation and delivery context;
2. translate a `PoolOperation`;
3. submit translated commands with explicit endpoint and correlation context
   through `VendorCommandGateway`;
5. return a structured operation-execution result.

This component must not replace the existing `ExecutionEngine`. During the
migration window, it is the operation-native handler registered with
`WorkDispatcher`; the legacy `Command` route continues through the current
`ExecutionEngine` until later milestones migrate it deliberately.

### 7. Multi-command translations are ordered but not implicitly atomic

`TranslationResult.commands` is an ordered tuple. Delivery will preserve that
order.

The initial delivery contract will use sequential, fail-fast behavior:

- commands are attempted in tuple order;
- delivery stops when a command is rejected or fails;
- receipts for every attempted command are retained;
- unattempted commands are reported explicitly;
- no rollback is implied.

PoolOS will not claim atomicity unless a concrete controller endpoint provides
a real transaction mechanism. Safety-critical compensating action belongs in
explicit orchestration/reconciliation logic, not in a generic gateway.

### 8. Acknowledgement and verification remain distinct

A successful `TransportResponse` or `CommandReceipt` does not prove that the
physical pool reached the requested state.

The delivery path may report:

- accepted;
- sent;
- acknowledged;
- rejected;
- failed;
- timed out.

`VERIFIED` requires authoritative observation and remains the responsibility of
state reconciliation. The gateway must not synthesize verification from a
transport acknowledgement.

### 9. Retry ownership is divided by failure type

Retry behavior is assigned as follows:

- **Transport endpoint:** short, protocol-safe retries for transient I/O where
  duplicate delivery is known to be safe or protected by protocol correlation.
- **Gateway:** no hidden semantic retry loop; it invokes an endpoint once per
  delivery request and records the result.
- **Execution/reconciliation:** decides whether the logical operation should be
  retried, replanned, compensated, or abandoned based on policy and observed
  state.

This prevents nested retry storms and preserves auditability.

### 10. Endpoint routing context must be explicit

The operation-to-installation context resolver must eventually provide a stable
`endpoint_id` in addition to vendor and equipment facts. The ID must not be
inferred from the vendor name or hidden inside arbitrary command metadata.

The implementation may introduce a dedicated execution context or extend the
existing immutable translation context, but routing must remain typed and
explicit. The final choice will be made in the first delivery implementation
milestone after reviewing compatibility impact.

## Dependency rules

Allowed dependencies:

```text
core domain/planning
    -> canonical PoolOperation types

integration translation
    -> PoolOperation, TranslationContext, VendorCommand

delivery
    -> VendorCommand, generic CommandReceipt, endpoint port

vendor endpoint implementation
    -> vendor command dialect, delivery endpoint port, HAL Transport

HAL Transport
    -> no PoolOperation or planning dependencies
```

Forbidden dependencies:

```text
planner -> VendorCommandGateway
translator -> Transport
Transport -> PoolOperation
HAL base contracts -> concrete Pentair command classes
runtime policy -> concrete vendor endpoint
VendorCommand -> live connection/session object
```

## Sequence diagrams

### Successful single-command operation

```text
WorkDispatcher
    -> OperationExecutionHandler: PoolOperation
OperationExecutionHandler
    -> context provider: resolve operation context
OperationExecutionHandler
    -> OperationTranslationHandler: translate
OperationTranslationHandler
    -> TranslatorRegistry: translate(vendor, operation, context)
TranslatorRegistry
    -> OperationTranslationHandler: TranslationResult
OperationExecutionHandler
    -> VendorCommandGateway: deliver(endpoint_id, command, correlation_id)
VendorCommandGateway
    -> endpoint registry: get(endpoint_id)
VendorCommandGateway
    -> VendorCommandEndpoint: deliver(command)
VendorCommandEndpoint
    -> Transport: send(destination, payload)
Transport
    -> VendorCommandEndpoint: TransportResponse
VendorCommandEndpoint
    -> VendorCommandGateway: CommandReceipt
VendorCommandGateway
    -> OperationExecutionHandler: CommandReceipt
OperationExecutionHandler
    -> WorkDispatcher: OperationExecutionResult
```

### Delivery acknowledgement followed by reconciliation

```text
VendorCommandEndpoint
    -> Transport: send
Transport
    -> VendorCommandEndpoint: acknowledged
VendorCommandEndpoint
    -> Execution path: CommandReceipt(ACKNOWLEDGED)

Later:

Observation path
    -> ReconciliationEngine: authoritative equipment state
ReconciliationEngine
    -> runtime: verified / retry / replan / fail
```

## Consequences

### Positive

- Translation remains pure and independently testable.
- HAL transport contracts remain free of planner and integration dependencies.
- One gateway provides a single audited route for vendor commands.
- Multiple controllers from the same vendor are supported by explicit endpoint
  identity.
- Vendor protocol serialization stays with vendor endpoint implementations.
- Simulator and future Home Assistant/RS-485 endpoints can share the same
  delivery contract.
- Acknowledgement is not confused with physical verification.

### Negative

- PoolOS gains a new delivery abstraction and registry.
- Translation plus delivery requires an orchestration component.
- Endpoint IDs and routing context must be modeled explicitly.
- Multi-command operation results require additional result types and tests.
- The migration temporarily retains both legacy `Command` execution and
  operation-native delivery paths behind `WorkDispatcher`.

### Risks

- The gateway could become a second execution engine if it acquires policy,
  scheduling, deduplication, or semantic retries.
- Endpoint implementations could leak transport-specific fields back into
  `VendorCommand`.
- Treating command batches as atomic without controller support could produce
  unsafe assumptions.
- Hiding endpoint identity in free-form metadata could make multi-controller
  routing fragile.

These risks are controlled by the ownership and dependency rules in this ADR.

## Rejected alternatives

### Add `deliver(VendorCommand)` to `HardwareAdapter`

Rejected because it couples generic HAL lifecycle/discovery contracts to the
integration command model and forces read-only adapters to implement a write
contract.

### Send `VendorCommand` directly through `Transport`

Rejected because the caller would need to know protocol serialization,
destination addressing, response interpretation, and vendor connection details.

### Let translators perform delivery

Rejected because translators must remain deterministic and free of I/O, retry,
connection, and credential concerns.

### Let `PoolRuntime` call transports directly

Rejected because runtime would become vendor/protocol aware and would bypass a
single auditable delivery boundary.

### Route only by vendor name

Rejected because one installation may have multiple writable controllers from
the same vendor.

### Put endpoint routing into arbitrary `VendorCommand.metadata`

Rejected as the long-term contract because routing is mandatory operational
state and requires typed validation.

### Reuse the legacy `ExecutionEngine` as the vendor-command gateway

Rejected for now because that engine owns generic command queuing, validation,
priority, execution records, and audit for the legacy `Command` model. Teaching
it vendor endpoint routing during migration would mix two contracts and expand
its responsibilities. A later unification may be considered only after the
operation-native path is stable and its invariants are explicit.

## Implementation roadmap

### Milestone 10.4B.3B — Delivery contracts only

Add, without real hardware I/O:

- `DeliveryReceipt`;
- `VendorCommandEndpoint` protocol;
- endpoint registry;
- `VendorCommandGateway`;
- structured routing/delivery errors;
- simulator/fake endpoint tests;
- no changes to planner, translator behavior, or existing HAL transports.

### Milestone 10.4B.3C — Operation execution composition

Add:

- operation execution context with explicit `endpoint_id`;
- `OperationExecutionHandler`;
- ordered translation-result delivery;
- structured per-command receipts and partial-failure reporting;
- registration as the `PoolOperation` route in `WorkDispatcher`;
- runtime wiring behind an opt-in composition path.

### Milestone 10.4B.3D — Simulator endpoint

Add a real vendor endpoint backed by `SimulatorTransport` to validate:

- serialization boundary;
- destination selection;
- receipt mapping;
- acknowledgement versus verification;
- multi-command fail-fast behavior.

### Later vendor transport milestones

Implement Pentair delivery through the chosen live transport, followed by
Home Assistant and/or direct RS-485 endpoints. Each endpoint must satisfy the
same gateway contract.

## Deferred decisions

- exact live Pentair payload format;
- Home Assistant service-call transport details;
- direct RS-485 framing and checksums;
- persistent delivery journal storage;
- distributed/multi-process endpoint registry;
- controller-supported transactions;
- command cancellation after transport submission;
- full retirement or redesign of the legacy `ExecutionEngine`.

## Compliance rules

A future change violates this ADR if it:

- lets a translator perform I/O;
- lets core planning or policy code select a transport;
- imports concrete vendor command classes into HAL base contracts;
- treats vendor name as sufficient endpoint identity;
- hides mandatory routing solely in untyped metadata;
- reports transport acknowledgement as physical verification;
- adds semantic retry, policy, or planning behavior to the gateway;
- creates a second direct transport write path outside registered endpoints.
