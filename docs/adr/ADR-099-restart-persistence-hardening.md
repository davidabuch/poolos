# ADR-099 — Restart Persistence and Shutdown Hardening

## Status

Accepted for PoolOS milestone 12.0C5.3 pending validation.

## Context

A controlled Home Assistant Core restart lasting roughly two minutes reset sustained native parity commissioning to a new post-restart history file even though the configured continuity allowance is five minutes. Live evidence showed the retained post-restart records were complete and separated by less than one minute, while all pre-restart records had disappeared. Home Assistant also reported that a PoolOS mapped-state observation task was still running after the final-writes shutdown stage.

The persistence format is append-only JSONL. Two restart hazards can therefore destroy an otherwise valid retained prefix: an interrupted final append can leave a partial trailing JSON record, and event-driven observations can be processed after a later-timestamped reconciliation cycle, making the on-disk append order non-chronological even though each record is individually valid. The previous loader treated either condition as corruption of the entire file and intentionally failed closed to empty history, after which the next valid cycle rewrote the file from scratch.

## Decision

1. Valid evidence records are kept chronologically ordered by `(generated_at, report_id)` in memory. An out-of-order arriving record forces an atomic full-history rewrite rather than an append.
2. On load, individually valid unique records that are merely out of chronological file order are deterministically sorted and marked for rewrite instead of discarding the entire evidence set.
3. A malformed **final JSON line only** is treated as an interrupted append. The valid prefix is retained, the history is marked for rewrite, and the next valid evidence cycle repairs the file. Malformed interior records, invalid schemas, invalid fields, or duplicate report identities still fail closed to empty history.
4. Append writes explicitly flush and `fsync` while already running in Home Assistant's executor boundary, reducing the chance of losing the final complete record during process shutdown.
5. PoolOS registers for `EVENT_HOMEASSISTANT_STOP` and quiesces mapped-state observation before Home Assistant reaches final-write shutdown. Existing config-entry unload protection remains in place.

## Safety invariants

This milestone does not change observation authority, parity tolerances, the five-minute continuity threshold, native mapping semantics, command delivery, physical delivery, or IntelliCenter protocol allowlists. Home Assistant remains authoritative and the independent IntelliCenter transport remains read-only. Evidence that is structurally ambiguous or internally corrupt still fails closed.

## Deployment rule

Validate locally and in CI before deployment. After deployment, perform one controlled Home Assistant Core restart and verify that pre-restart history remains present and `continuous_evidence_hours` survives when the complete-evidence gap is no greater than five minutes.
