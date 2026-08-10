# ADR-090 — Expected-Outage Operator Annotation

## Status

Accepted for PoolOS milestone 11.6.1.

## Context

PoolOS cannot know why upstream observations disappear when they become
unavailable. A known interruption may be acknowledged before, during, or after
the actual incident. That context must be durable without suppressing live
health or rewriting observation truth.

## Decision

PoolOS adds an immutable `ExpectedOutageAcknowledgment` to the existing
append-only observation evidence store. The Home Assistant diagnostic button
records an acknowledgment at timestamp `T`; the centralized default matching
policy spans `T - 2 hours` through `T + 2 hours`.

The matching window is only a search interval, never the outage duration. An
actual incident matches when its independently constructed interval intersects
the acknowledgment window, including exact boundary contact. Multiple incidents
remain distinct. Repeated acknowledgments remain ordered provenance and cannot
duplicate incidents.

Processing order is:

1. preserve raw observation and health evidence;
2. apply ADR-088 startup calibration;
3. construct actual neutral observation incidents;
4. classify intersecting incidents from durable operator acknowledgments; and
5. compute retrospective quality and cross-day readiness.

This prevents startup-only transients from becoming incidents because an
annotation exists.

## Quality and learning semantics

Raw healthy coverage, unavailable/stale durations, evidence IDs, incident
start/end, and duration remain unchanged. Additive fields separately expose
expected and unexpected counts and commissioning-adjusted reliability evidence.

Expected intervals do not create an unexplained reliability penalty or reset
multi-day days-without-unexpected-incidents readiness. They remain provenance.
Solar transitions or episodes supported by an expected interval are excluded
from learning; missing evidence is never imputed. Independent coverage or gap
failures may still degrade or exclude a day.

## Persistence and export

Acknowledgments use deterministic identities, timezone-aware timestamps, and
the retained observation JSONL store. Observation queries ignore annotation
records; annotation queries restore and deduplicate them by identity. Daily
JSONL/CSV exports include raw health evidence and explicit acknowledgment
timestamp, window, classification, source, and identity. Retrospective
serialization contains the matched acknowledgment and actual incident interval.

## Safety boundary

The button writes only local PoolOS annotation evidence. It is available during
healthy or unhealthy operation and does not clear live health or the separate
incident latch. It cannot call an equipment service, restart IntelliCenter,
write Pentair, perform network/vendor work, create policy, increase authority,
or actuate equipment. PoolOS remains OBSERVE-only with authority NONE and
command delivery disabled.

## Consequences

Expected maintenance can be distinguished from unexplained reliability
incidents without hiding the outage. Interpretation changes only when explicit
durable operator evidence intersects an actual incident.
