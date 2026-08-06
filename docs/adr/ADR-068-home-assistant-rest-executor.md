# ADR-068: Home Assistant REST executor

- **Status:** Accepted
- **Milestone:** 10.19A
- **Date:** 2026-08-05

## Context

The reviewed execution pipeline now reaches an immutable
`HomeAssistantServiceCall` and invokes a caller-supplied executor. The complete
path has been validated with a mock executor, but no production-capable network
boundary exists for authenticated Home Assistant delivery.

PoolOS already contains an older Home Assistant REST executor used by a separate
command-client path. The new supervisory execution pipeline must not depend on
that older service-call model or create an additional transport abstraction.
It needs a callable implementation of the executor contract already accepted by
`HomeAssistantTransportAdapter`.

## Decision

Add `HomeAssistantRestExecutorConfig` and `HomeAssistantRestExecutor` in the
supervisory execution layer.

The executor:

1. accepts only the immutable service call produced by the existing transport
   adapter;
2. performs one synchronous authenticated `POST` to
   `/api/services/{domain}/{service}`;
3. combines the prepared target and data into Home Assistant's REST payload;
4. returns a mapping containing the HTTP status, response body, extracted
   context identity, and PoolOS service-call identity;
5. classifies authentication, authorization, service rejection, server failure,
   timeout, connection failure, and malformed-response outcomes with sanitized
   exception types;
6. accepts an injected HTTP sender for deterministic tests;
7. keeps the access token out of representations, returned evidence, provenance,
   and error messages.

The standard-library HTTP client is sufficient for this bounded synchronous
request and avoids adding a runtime dependency.

## Safety boundary

This milestone does not add retry, backoff, WebSocket lifecycle management,
background work, state observation, physical-state verification,
reconciliation, commissioning, credential discovery, or automatic live-mode
enablement. Constructing the executor does not send a request; actuation occurs
only when an explicit caller invokes it through the existing delivery path.

A successful REST response is delivery evidence only. It is not proof that the
physical pool equipment reached the requested state.

## Consequences

- The existing execution pipeline gains a production-capable Home Assistant
  delivery implementation without changing upstream contracts.
- HTTP behavior and credential handling are independently testable without a
  live Home Assistant instance.
- Failures remain visible to the existing adapter as deterministic executor
  failures.
- Post-command observation, reconciliation, retries, and commissioning remain
  separate future milestones.
