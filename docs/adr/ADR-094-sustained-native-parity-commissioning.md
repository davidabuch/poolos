# ADR-094 — Sustained Native Parity Commissioning

## Status

Accepted for PoolOS milestone 12.0C3.

## Context

ADRs 091–093 established an independent read-only IntelliCenter observation
path, reviewed native semantics, explicit parity eligibility, and comparison-
cycle freshness. A single near-perfect parity snapshot cannot establish
long-term acquisition trust. Transient sampling differences, disconnects,
reconnect loops, model rediscovery, stale evidence, and persistent mapping
errors must be distinguishable over normal operation before any later source-
authority proposal can be reviewed.

The initial commissioning target is 72 continuous hours. The observed
approximately one-degree solar-temperature difference remains a real parity
result under the existing 0.5°F tolerance; C3 gathers evidence and does not
weaken that tolerance.

## Decision

### Persistent shadow evidence

After each IntelliCenter parity comparison, PoolOS appends one versioned,
privacy-safe record to
`/config/poolos_logs/native_parity_history.jsonl`. Each record contains aggregate
counts, transport availability/state, reconnect and discovery generation
counters, and the eligible per-concept status, values, tolerance, numeric delta,
HA source/sample times, and native observation time.

Only concepts in the explicit IntelliCenter parity domain are admitted.
Excluded grid and HA-only concepts cannot become persisted commissioning
failures. Source IDs, controller names, hosts, addresses, credentials, raw
inventory, and personal/location data are not serialized.

The store atomically replaces a human-readable summary at
`/config/poolos_logs/native_parity_commissioning.json`. The summary is safe to
upload for review and contains no communication or control capability.

### Retention and recovery

History retains seven days and at most 30,000 records. This covers the 72-hour
target at the normal refresh cadence. Retention is swept at most hourly during
normal operation so the append path does not rewrite several days of evidence
every cycle; the record-count ceiling remains immediate. Startup validates and
reconstructs the retained window deterministically.

Malformed, incompatible, or duplicate history fails closed to an empty in-
memory window and an explicit persistence error. It does not crash Home
Assistant or alter authoritative HA observations. New parity can continue in
memory. Disk failures likewise affect only commissioning persistence.

### Transient and persistent evidence

Every non-match status remains unchanged in raw evidence. Per-concept summaries
count matches, value/type mismatches, missing HA/native evidence, and stale
HA/native evidence. Numeric absolute delta is calculated only for comparable
non-boolean numbers; maximum and mismatch-average deltas remain explicit.

Current and longest consecutive adverse runs, their measurable duration, and
time since last match distinguish transient from persistent evidence without
downgrading either. Three current consecutive adverse cycles are labeled
persistent for review presentation; the underlying statuses are not changed.

### Duration and transport stability

The report tracks both total retained elapsed time and the current continuous
evidence duration. A native-unavailable, missing, or stale comparison cycle, or
a gap longer than five minutes, resets the continuous run. Reconnect increments,
discovery-generation changes, unavailable cycle count, and maximum evidence gap
are reported as neutral stability evidence. A reconnect alone is not treated as
catastrophic.

The compact HA diagnostic uses neutral states:

- `COLLECTING` before a useful sequence exists;
- `INSUFFICIENT_DURATION` before the continuous 72-hour target;
- `DEGRADED` after the target when current persistent adverse evidence or
  transport-unavailable cycles remain in the retained review window; and
- `READY_FOR_REVIEW` after the target without those conditions.

These are manual-review readiness states. They are not authority, approval, or
an execution gate. Full cycle history and per-concept statistics are kept out
of Home Assistant state attributes.

## Safety and authority

HA-derived observations remain the only authoritative operational facts. C3
evidence does not feed observation health, authoritative recording, behavioral
inference, retrospectives, multiday commissioning, recommendations, decisions,
execution, delivery, or physical control.

Authority remains NONE. Command and physical delivery remain disabled. The
transport allowlist remains exactly `GetParamList` and `RequestParamList`; C3
adds no protocol, socket, Home Assistant service, or equipment-mutation path.

## Consequences

PoolOS can survive restart and measure whether native acquisition remains
stable across real operation while preserving every mismatch for analysis. A
72-hour `READY_FOR_REVIEW` result supplies evidence for human review only. Any
future native-source selection or authority change requires a separate explicit
architectural and safety decision.
