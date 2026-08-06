# ADR-063: Transport Delivery Gateway

- **Status:** Accepted
- **Milestone:** 10.16I
- **Date:** 2026-08-05

## Context

ADR-062 established a deterministic vendor-translation boundary that produces
ordered `VendorCommand` objects without delivering them. PoolOS still needs a
separate boundary that decides which logical transport adapter would receive
each translated command while preserving the complete upstream evidence chain.

Transport selection must remain independent from live delivery. Home Assistant,
MQTT, REST, simulator, or future adapters must not be invoked merely because a
route was selected.

## Decision

Introduce `TransportDeliveryGateway` as a pure, deterministic preparation
boundary.

The gateway:

- accepts only a successful `VendorTranslationBoundaryResult`;
- preserves vendor-command order across execution steps;
- obtains one explicit `TransportRoute` per command from a caller-supplied
  resolver;
- creates one immutable `TransportDeliveryRequest` per command;
- derives stable gateway and delivery-request identities from canonical input;
- preserves translation, dispatch, schedule, authorization, plan, proposal,
  decision, context, operation, step, and correlation evidence;
- rejects invalid route returns or resolver failures without exposing partial
  delivery requests.

The gateway does not instantiate or invoke adapters. It performs no network
operation, Home Assistant service call, MQTT publish, HTTP request, vendor call,
acknowledgement, retry, verification, persistence, or physical actuation.

## Consequences

### Positive

- Transport routing remains independently testable and replayable.
- Live adapter side effects remain behind a later explicit delivery boundary.
- One translated step may safely expand to multiple ordered delivery requests.
- Partial routing is never presented as a successful gateway result.
- Future transports can be added without changing decision or translation code.

### Negative

- Callers must supply a deterministic route resolver.
- Route availability is declarative at this stage; operational connectivity is
  evaluated later.
- Delivery acknowledgements and retry policy remain intentionally unresolved.

## Follow-up

A later milestone may introduce a transport adapter invocation boundary that
consumes `TransportDeliveryRequest` objects and produces immutable delivery
receipts. That boundary must preserve the no-implicit-actuation rule and keep
transport-specific failures outside the planning and translation layers.
