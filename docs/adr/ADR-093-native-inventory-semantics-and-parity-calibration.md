# ADR-093 — Native Inventory Semantics and Parity Calibration

## Status

Accepted for PoolOS milestone 12.0C2, with post-commissioning privacy hardening.

## Context

ADR-092 established an independent, structurally read-only IntelliCenter
connection and immutable raw inventory. Live commissioning confirmed that the
connection is independent and available, but exposed two calibration needs.

First, canonical HA observations preserve the entity's last report timestamp.
That timestamp is correct for operational health and historical evidence, but
an unchanged current HA state can remain in HA's state cache for hours. Applying
the parity engine's five-minute threshold to that source timestamp falsely
classifies a successful current-cycle read as `STALE_HA`.

Second, the authoritative HA snapshot includes facts outside IntelliCenter's
hardware domain. Grid/Powerwall facts cannot have native counterparts and must
not lower IntelliCenter parity. Conversely, valid controller concepts must not
be hidden merely because native mapping is incomplete.

Live review of the first complete native inventory also showed that some raw
SYSTEM, SYSTIM, and PERMIT attributes can contain credentials, contact details,
precise location data, controller/user names, and occupancy-related dates. Those
values are not required for PoolOS commissioning and must not be persisted in a
routine diagnostic export.

## Decision

### Source time and parity sample time

PoolOS preserves every canonical HA observation's `observed_at` source/report
timestamp. The operational freshness policy, context-sensitive pump and
temperature requirements, health, recording, inference, retrospectives, and
commissioning continue using that timestamp exactly as before.

For IntelliCenter shadow comparison only, the coordinator supplies explicit
per-concept sample times for good observations read from HA's current state
cache during that comparison cycle. The parity engine uses sample time for HA
comparison freshness when present and retains both source time and sample time
in deterministic diagnostics. Evidence without a valid current-cycle sample can
still become `STALE_HA`; native evidence continues using its own observation
time and can still become `STALE_NATIVE`.

### IntelliCenter parity eligibility

The native adapter owns one immutable parity-eligible concept set. It contains
facts IntelliCenter can directly provide or validly lacks today. Grid facts are
excluded because they belong to Powerwall, not IntelliCenter. HA HVAC mode and
action strings and light color/effect abstractions are excluded because current
native evidence does not expose directly equivalent semantics. Excluded
concepts are reported separately and do not enter the denominator.

Missing eligible native concepts remain `MISSING_NATIVE`; the eligibility rule
cannot be used to conceal incomplete mapping.

### Reviewed native semantics

BODY `HEATER` and `HTMODE` are copied verbatim into pool/spa raw canonical
diagnostic concepts when present. Their absence remains missing. Pool Light
power state is mapped only when exactly one circuit has the explicit `INTELLI`
subtype and Pool Light identity. Color and effect remain unmapped.

The audited pyintellicenter model documents SENSE `SOURCE` as the calibrated
reading, `PROBE` as the uncalibrated reading, and `SUBTYP` values `AIR`, `SOLAR`,
and `POOL` for air, solar, and water. PoolOS uses those exact subtype values and
does not infer sensor semantics from names or parents. Unknown and ambiguous
probes remain raw inventory. A live value mismatch remains visible until
evidence explains it.

### Complete inventory export

The HA inventory sensor remains capped at 20 objects and retains explicit
truncation metadata. Separately, PoolOS atomically replaces
`/config/poolos_logs/native_intellicenter_inventory.json` using the existing
PoolOS logs root. The deterministic JSON contains every immutable raw object,
bounded attribute names and scalar values, software/transport metadata,
discovery generation, timestamps, and explicit safety metadata. It contains no
capability that can communicate with equipment.

The export schema is versioned. Schema version 2 applies privacy redaction
before serialization. Credential-like attributes are redacted globally, and
SYSTEM/SYSTIM attributes that can expose contact information, precise location,
user/controller identity, or occupancy-related dates are redacted while their
attribute names remain visible for protocol analysis. SYSTEM display names are
redacted and controller name is omitted from exported transport metadata.
Technical equipment identity, firmware, status, schedules, sensor readings,
pump data, circuit data, and other non-sensitive commissioning evidence remain
available. The payload reports redaction status/count so reviewers know that the
export is intentionally privacy-filtered rather than raw.

Additional observed types such as FDR, FEATR, MODULE, PANEL, PERMIT, PRESS,
REMBTN, REMOTE, STATUS, SYSTIM, and VALVE are retained without invented semantic
concepts. Future unknown types degrade the same way.

## Safety and authority

The independent transport allowlist remains exactly `GetParamList` and
`RequestParamList`. `SetParamList` and all equipment mutation, HA control
services, direct socket writes, command delivery, and physical delivery remain
inaccessible. Authority remains NONE. HA-derived observations remain the sole
authoritative input to health, recording, intelligence, recommendations,
decisions, execution, and commissioning.

## Consequences

Parity now measures a successful current comparison rather than the age of an
unchanged HA cache entry, while operational freshness remains untouched. The
denominator describes the IntelliCenter domain explicitly and cannot be inflated
by hiding missing valid concepts. Complete technical native evidence is
available for review without expanding Recorder attributes or persisting
credentials and personal/location data unnecessarily.

Milestone 12.0C3 must collect sustained parity evidence and resolve remaining
live discrepancies. C2 does not make native observations authoritative or
selectable.
