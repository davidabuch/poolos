# ADR-084 — Persistent Observation + Event Recorder

**Status:** Accepted
**Milestone:** 11.3B

## Context

The 11.1 observation bridge and shadow runtime expose current Home Assistant state, but 11.3C behavioral inference requires durable evidence across restarts and across multiple days. Persisting every 30-second coordinator poll would duplicate unchanged state, increase write load, and make later reasoning noisier.

PoolOS must preserve the architectural distinction between observed facts and inferred behavior. Historical storage therefore records canonical observations and observation-health evidence only; it does not infer operating modes and cannot create commands.

## Decision

PoolOS adds a vendor-independent `PersistentObservationRecorder` under `poolos.observations` and connects it to the read-only Home Assistant coordinator.

The recorder writes append-only UTC-day JSONL files beneath the PoolOS Home Assistant storage directory. Each durable record is a composite evidence snapshot containing:

- a deterministic SHA-256 event identity derived from canonical record content;
- record timestamp and schema version;
- record kind (`baseline`, `transition`, `health_transition`, or `checkpoint`);
- changed canonical observation IDs;
- canonical values, units, truth level, timestamps, source/provenance, quality, confidence, and evidence;
- observation-bridge health state.

The Home Assistant observation bridge also adds optional `solar.temperature` and `air.temperature` mappings so roof/solar and ambient temperature evidence can be persisted for later solar-behavior inference without hard-coding installation-specific entity IDs.

A new recorder instance writes a baseline on its first snapshot, including after Home Assistant restart. Thereafter it suppresses unchanged 30-second polls. Boolean/state changes are recorded immediately. Numeric signals use conservative significance thresholds (25 RPM, 0.1°F, and 50 W for the currently commissioned signals), while a five-minute checkpoint preserves trend and energy evidence even when changes remain below those thresholds.

History is divided into daily files and retained for 35 UTC days by default. Pruning occurs during successful writes. Time-window queries return records deterministically by timestamp and event identity.

Home Assistant file writes run in its executor rather than on the event loop. A storage or serialization error from the recorder is logged and does not prevent the coordinator from returning its current snapshot or running the shadow intelligence path. Recorder diagnostics expose health and counters without exposing raw pool values.

## Safety boundary

11.3B does not register Home Assistant services, expose control entities, call Home Assistant equipment services, construct commands, authorize execution, or deliver actuation. Operating mode remains `OBSERVE`, authority remains `NONE`, and command delivery remains disabled.

## Consequences

11.3C can replay durable observed evidence without treating inference as fact. 11.3D can later compute daily actual-operation metrics from the same evidence. Storage load remains bounded by retention and reduced by transition/checkpoint recording rather than unconditional polling persistence.
