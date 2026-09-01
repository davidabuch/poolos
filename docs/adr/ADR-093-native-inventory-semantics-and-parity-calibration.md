# ADR-093 — Native Inventory Semantics and Parity Calibration

## Status

Accepted for PoolOS milestone 12.0C2, with post-commissioning privacy hardening;
extended by ADR-094 for milestone 12.0C3.

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

The reviewed remaining operator surface uses the same immutable path. An
IntelliChlor `CHEM/ICHLOR` object contributes `SALT`, `PRIM`, and `SEC`; its
ordered `BODY` relationship determines whether each configured percentage
belongs to Pool or Spa. BODY `HITMP` is the body's maximum-temperature
configuration rather than its normal `LOTMP` thermostat target. PUMP `MIN` and
`MAX` are read-only hardware constraints and are published only when both are
positive and ordered. CIRCUIT subtype `FRZ` uses `STATUS` for observed freeze
state. SYSTEM `VER` and `SERVICE` provide firmware and a normalized
auto/service/timeout mode; unknown future modes remain unavailable rather than
being invented.

These concepts remain observation-first. Salt, BODY maximum temperature,
SYSTEM state, and pump limits are read-only. IntelliChlor Pool and Spa output
percentages additionally have bounded manual number controls after audit of
pyintellicenter 0.1.20 and the working legacy integration proved the native
`set_chlorinator_output` contract. The command gateway accepts only the single
commissioned `CHR01` ICHLOR object, derives `PRIM`/`SEC` ownership from its
ordered `BODY` relationship, accepts whole percentages from zero through 100,
and fails closed on missing or ambiguous objects. A secondary-output request
preserves the current authoritative primary output because the library's
secondary write sends both fields. The entity never changes its displayed value
from command acceptance; later independent native read-back remains truth.
Optional legacy HA mappings remain independent parity inputs during retirement
commissioning.

### Canonical manual thermal intent

The Pool and Hot Tub heat-mode selects own requested operator thermal mode.
Direct Off, Gas, and Solar requests use one bounded body/HEATER command path;
Solar Preferred changes PoolOS policy intent only and never writes Pentair's
legacy Solar Preferred mode. Native HEATER and active-source observations remain
separate authoritative truth.

The Pool Solar switch is only a convenience proxy into that same Pool requested
mode path. Solar ON requires current Pool activity and native source evidence,
then requests direct Solar. Solar OFF is a no-op when native Off or Gas is
selected, so it cannot accidentally deselect Gas. It may request direct Off only
when native direct Solar and requested direct Solar agree. Unknown source,
contradictory requested intent, and Solar Preferred intent fail closed. No Gas
switch is added because the canonical heat-mode select already represents Gas.

### Intentional migration boundary

PoolOS does not mirror IntelliCenter schedules, Vacation Mode,
operation-specific RPM presets, duplicate Pool/Spa/environment temperatures,
direct Pool/Spa hydraulic activation controls, or obsolete Solar Preferred
entity surfaces. There remains one persistent configured Pool RPM baseline;
temporary operating RPM belongs to planning, and actual RPM remains observed
equipment truth.

Native IntelliChlor Super Chlorinate is also intentionally not migrated. Its
raw field may remain in privacy-safe inventory for protocol forensics, but it
has no PoolOS canonical concept, parity requirement, entity, or write path. A
future PoolOS-owned super-chlorination feature, if separately designed and
commissioned, will orchestrate a bounded temporary normal Pool-output target
of 100 percent and then re-evaluate or restore normal output. That policy
requires explicit duration, restart, recovery, restoration, safety, and
commissioning semantics and is not part of native observation parity.
The bounded normal-output numbers do not expose `SUPER`, persist a pending
boost, or provide autonomous chemistry authority.

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
