# ADR-064: Home Assistant transport adapter

- **Status:** Accepted
- **Milestone:** 10.17A
- **Date:** 2026-08-05

## Context

Epic 10.16I ends with immutable `TransportDeliveryRequest` objects. PoolOS now
needs its first concrete transport adapter, but the adapter must not absorb
planning, policy, retry, reconciliation, or vendor-domain responsibilities.

Home Assistant service calls are represented by a domain, service, target, and
data payload. Direct network communication and authentication remain outside
this milestone so the adapter can be validated without a live Home Assistant
instance.

## Decision

Add `HomeAssistantTransportAdapter` as a narrow boundary that:

1. accepts one `TransportDeliveryRequest` routed to the Home Assistant transport;
2. validates the logical transport, adapter name, and `domain.service` endpoint;
3. constructs an immutable `HomeAssistantServiceCall`;
4. invokes only a caller-supplied executor;
5. returns immutable delivered, failed, or rejected evidence;
6. preserves upstream identity and provenance.

The adapter places the vendor command target in Home Assistant's `entity_id`
target field. Vendor-command parameters become service data, augmented only by
traceability fields for vendor, operation, and delivery-request identity.

## Safety boundary

The module contains no direct HTTP, WebSocket, Home Assistant SDK, credential,
retry, backoff, acknowledgement interpretation, state reconciliation, or
physical-control code. A production executor may be added at a later boundary.

## Consequences

- The Home Assistant service-call contract becomes independently testable.
- Executor failures are recorded without hiding the prepared service call.
- PoolOS business rules remain upstream of transport delivery.
- Authentication, retries, and state verification require later milestones.
