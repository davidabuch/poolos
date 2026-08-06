# ADR-062: Vendor Translation Boundary

## Status

Accepted for Epic 10.16H.

## Context

Epic 10.16G introduced immutable dispatch-request evidence for scheduled execution plans. PoolOS already contains a transport-independent integration framework that translates canonical `PoolOperation` objects into immutable `VendorCommand` objects through `OperationTranslationHandler` and `TranslationResult`.

The next responsibility is to compose those existing contracts at the dispatch boundary without introducing transport selection, network delivery, acknowledgement handling, retries, or physical actuation.

## Decision

Introduce `VendorTranslationBoundary` as a deterministic, non-delivering boundary.

The boundary:

1. accepts one `ExecutionDispatchBoundaryResult`;
2. requires a ready, internally consistent `ExecutionDispatchRequest`;
3. visits execution-plan steps in canonical sequence order;
4. delegates each step's `PoolOperation` to a caller-supplied operation translator;
5. records immutable per-step `VendorTranslatedStep` evidence;
6. returns ordered transport-neutral `VendorCommand` objects and complete provenance.

Translation identity is derived from stable dispatch, step, operation, warning, and command content. No wall-clock read participates in identity.

Integration-framework failures are converted into deterministic rejected evidence. A failed step produces no partial translated-step result.

## Boundaries

Epic 10.16H does not:

- select a transport or vendor connection;
- call Home Assistant, Pentair, MQTT, HTTP, RS-485, or any network service;
- deliver, retry, acknowledge, verify, or persist commands;
- mutate plan, schedule, dispatch, or equipment state;
- actuate physical equipment.

## Consequences

PoolOS gains a reviewed handoff from ready dispatch evidence to ordered vendor-command evidence while preserving the existing integration framework and hardware-independent execution architecture. A later milestone may deliver translated commands through explicit transport adapters.
