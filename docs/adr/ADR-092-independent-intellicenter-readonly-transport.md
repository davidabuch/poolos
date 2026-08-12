# ADR-092 — Independent IntelliCenter Read-Only Transport and Raw Discovery

## Status

Accepted for PoolOS milestone 12.0C1.

## Context

ADR-091 established immutable native snapshots, deterministic normalization,
and parity while temporarily borrowing a copied snapshot from a separate Home
Assistant IntelliCenter integration. That seam proved the mapping and parity
architecture, but it did not give PoolOS an independent hardware connection.

PoolOS must discover the controller's actual native data surface before it can
review deterministic mappings or consider a native observation source. The
existing Home Assistant integration remains valuable as an independently
implemented reference oracle during commissioning. Its HA-derived observations
remain authoritative.

`pyintellicenter` already implements the deployed controller's TCP and WebSocket
session, discovery, update subscription, keepalive, and bounded reconnect
behavior. Its general-purpose controller also exposes mutation methods, so that
controller cannot be part of PoolOS's public transport contract.

## Decision

PoolOS owns one independently configured IntelliCenter connection inside the
Home Assistant integration. The configured host and transport are PoolOS entry
data; PoolOS does not read the reference integration's `runtime_data`,
coordinator, API snapshot, entities, or connection.

The public PoolOS transport surface is narrow: start, stop, connection state,
latest immutable snapshot, snapshot read, and bounded diagnostics. A private
controller and model implement the connection. No controller, model object,
socket, or command method is returned to callers.

The transport copies protocol state into frozen PoolOS values. The snapshot
contains the supported 12.0A normalized read fields plus a deterministically
ordered raw inventory. Each raw record preserves native object identity, type,
subtype, name, parent, observed time, available tracked attribute names, and
defensively copied scalar values. Known discovery types include BODY, CIRCUIT,
CIRCGRP/CIRCGROUP, HEATER, PUMP, PMPCIRC, SENSE, CHEM, SCHED, EXTINSTR, and
SYSTEM. Unexpected object types are retained with conservative identity
attributes rather than discarded or assigned guessed semantics.

Only unambiguous fields already supported by the existing
`NativeIntelliCenterReadAdapter` enter canonical native observations and parity.
Other evidence remains raw inventory for 12.0C2 review. The parity engine,
tolerances, freshness rules, and source-of-truth policy do not change.

## Structural read-only boundary

PoolOS pins the audited `pyintellicenter` version and subclasses its controller
only inside the transport module. Every controller command crosses one central
allowlist. The only admitted protocol operations are:

- `GetParamList`, used for controller identity, object discovery, parameter
  reads, and keepalive reads; and
- `RequestParamList`, used to subscribe to model state updates.

These messages establish and maintain a read session; they do not request a
change to equipment state. Session framing is owned by the pinned library.
PoolOS contains no direct socket send or write path.

All other controller operations fail before reaching the connection. In
particular, `SetParamList`/`SETPARAMLIST`, controller `request_changes`, queued
property changes, circuit state, heater or setpoint changes, pump speed or flow,
body mode, light effects, chemistry changes, and schedule changes are not
available through the public boundary. The central guard also counts blocked
attempts for diagnostics. Home Assistant equipment-control service calls are
absent.

Authority remains `NONE`. Command delivery and physical delivery remain
disabled. The presence of a live read connection grants no execution authority.

## Lifecycle and failure isolation

The PoolOS config-entry lifecycle owns at most one transport instance. Setup
starts it without blocking authoritative observation refresh; unload cancels
startup/reconnect work and closes the connection. The pinned library's bounded
reconnect handler is retained. State transitions expose initialization,
connecting, discovery, available, disconnected, reconnecting, and unavailable
conditions.

Connection, discovery, update, malformed-object, disconnect, and reconnect
failures affect only native shadow status and parity. HA-derived observations
continue through recording, inference, retrospectives, commissioning,
recommendations, decisions, and shadow runtime without native evidence.

Diagnostics expose connection and discovery timestamps, controller identity and
software version when available, snapshot age, reconnect and generation counts,
object counts by type, unknown-type count, errors, allowed and blocked operation
evidence, and bounded raw inventory. Inventory is deterministically truncated
and targets substantially less than Home Assistant's 16 KB Recorder limit.

## Consequences

PoolOS can inspect its controller independently while comparing supported facts
against the still-installed reference integration. It gains a vendor-specific
observation transport at the integration edge without contaminating the
vendor-independent core or creating an actuation path.

The exact native inventory and some subtype meanings remain installation- and
firmware-dependent. Milestone 12.0C2 must review collected identities before
adding mappings. Milestone 12.0C3 must establish sustained parity before native
evidence can be considered for authority selection. Neither milestone may infer
semantic meaning merely from display names.
