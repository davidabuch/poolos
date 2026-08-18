# ADR-100 — Commissioning Restart Continuity Grace

## Status

Accepted for PoolOS milestone 12.0C5.4 pending validation.

## Context

Live Home Assistant restart testing after 12.0C5.3 proved that native parity history now survives Core restarts. A later controlled restart retained the complete history and produced no evidence gap greater than five minutes, but one transient startup parity cycle contained five missing native concepts. The commissioning clock reset because the existing continuity algorithm treated any incomplete cycle as an immediate break.

This behavior is stricter than the intended commissioning contract. Home Assistant and the independent IntelliCenter shadow transport can repopulate asynchronously during a short Core restart. A transient incomplete sample should remain visible as diagnostic evidence without erasing an otherwise continuous multi-hour commissioning window when complete evidence resumes within the configured five-minute allowance.

## Decision

1. All parity records remain persisted and continue to contribute to diagnostic mismatch, transport, and availability statistics.
2. Continuous commissioning duration is anchored by complete parity records.
3. Incomplete records do not immediately reset continuity. They create a grace interval.
4. If complete parity evidence resumes within the configured maximum continuous gap, the prior continuous window is preserved across that short interruption.
5. If the interval since the last complete parity record exceeds the maximum continuous gap, continuity is broken. A later complete record starts a new continuous window.
6. The existing maximum raw evidence-gap diagnostic remains based on adjacent persisted records and is not hidden or relaxed.

## Safety invariants

This change does not alter parity eligibility, tolerances, observation authority, transport protocol allowlists, native mappings, command authority, command delivery, or physical delivery. Home Assistant remains authoritative and the independent IntelliCenter transport remains shadow/read-only.

## Live acceptance criterion

After deployment, a normal short Home Assistant Core restart may produce transient incomplete startup parity cycles, but if complete parity evidence resumes within five minutes, `continuous_evidence_hours` must continue from the pre-restart window rather than reset. A gap beyond five minutes must still break continuity.
