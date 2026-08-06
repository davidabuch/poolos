# ADR-065: Home Assistant Delivery Acknowledgement

- Status: Accepted
- Date: 2026-08-05
- Milestone: 10.17B

## Context

The Home Assistant transport adapter produces immutable delivery results, but
later execution stages require a stable representation of whether Home
Assistant acknowledged the request, reported failure, timed out, or was
unavailable. Adapter-specific mappings must not leak into retry, reconciliation,
or supervisory logic.

## Decision

Add a deterministic acknowledgement boundary that consumes one
`HomeAssistantDeliveryResult` plus explicit observation time and optional
outcome evidence. It produces immutable canonical acknowledgement evidence with
one of these dispositions:

- `ACKNOWLEDGED`
- `FAILED`
- `TIMED_OUT`
- `UNAVAILABLE`
- `REJECTED`

The boundary preserves upstream identities and raw acknowledgement data. It
performs no Home Assistant call, retry, backoff, state reconciliation, or
physical actuation.

## Consequences

- Later retry and reconciliation components receive transport-independent,
  stable outcome evidence.
- Time remains explicit and deterministic.
- Existing adapter failures are normalized without being retried.
- State verification remains a separate future boundary.
