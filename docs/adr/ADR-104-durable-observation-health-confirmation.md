# ADR-104: Durable Observation-Health Confirmation

Status: accepted

## Context

PoolOS must fail closed as soon as current observation evidence is unhealthy.
However, the diagnostic incident latch and daily retrospective previously
promoted one unhealthy evaluation even when the next healthy evaluation
arrived only milliseconds later. That conflated immediate command safety with
durable operational history.

## Decision

Immediate `ObservationSnapshot.healthy`, current observation-health state, and
thermal authorization gates remain unchanged and fail closed on the first bad
evaluation.

Durable coordinator diagnostics use a separate immutable confirmation state.
The first unhealthy snapshot outside startup grace creates a pending candidate.
A second consecutive unhealthy snapshot with a different canonical
`ObservationSnapshot.generated_at` confirms the incident and preserves the
first timestamp. Republishing or reevaluating the same immutable snapshot does
not confirm it. A healthy snapshot clears an unconfirmed candidate; a confirmed
latch survives recovery until the existing explicit reset, which also clears
pending state. Startup-grace evidence neither latches nor seeds a candidate.

The retrospective independently qualifies persisted evidence. It emits an
incident when there are two distinct consecutive unhealthy event identities,
or when one unhealthy record has bounded carried-forward evidence for at least
30 seconds. Thirty seconds is the existing PoolOS reconciliation cadence, and
the existing 15-minute maximum evidence-gap rule still bounds carried-forward
support. Thus a 63-millisecond unhealthy/healthy transition remains raw
evidence but is not promoted, while a sparse sustained outage remains visible.
Expected-outage classification and multiday commissioning consume only the
resulting qualified incidents.

## Consequences

- No timer, sleep, polling loop, or background confirmation task is added.
- Immediate stale, unavailable, missing, or unhealthy evidence still blocks
  physical authority on its first evaluation.
- Durable diagnostics expose pending and confirmed states separately.
- Missing, unavailable, and stale provenance is retained across a confirmed
  unhealthy run.
