# ADR-091 — Native IntelliCenter Read-Only Parity Boundary

## Status

Accepted for PoolOS milestone 12.0A.

## Context

PoolOS commissioning currently receives IntelliCenter facts through entities
published by a separate Home Assistant IntelliCenter integration. That bridge is
useful for commissioning but cannot remain a production installation
requirement. PoolOS must eventually own the IntelliCenter interface while
preserving its observation-first safety model.

The repository already contains a stable immutable IntelliCenter protocol read
model alongside a Home Assistant integration whose coordinator also owns
write-capable controller internals. PoolOS must reuse read evidence without
importing or exposing those controller capabilities.

## Decision

PoolOS adds a vendor-specific but core-owned read-only boundary consisting of:

- immutable minimal native transport snapshot types;
- a `NativeIntelliCenterReadSource` protocol exposing only `read_snapshot`;
- a deterministic adapter from transport facts to canonical `PoolObservation`;
- distinct `intellicenter_native:` provenance and explicit missing concepts;
- typed `INITIALIZING`, `AVAILABLE`, and `UNAVAILABLE` source states; and
- a deterministic parity engine comparing native and HA-derived canonical
observations with explicit per-concept outcomes.

Native metric temperatures are normalized to the existing canonical Fahrenheit
contract. A sole pump/probe, one clearly named primary device, or one uniquely
running pump may be selected; ambiguous inventories remain explicitly missing
rather than being guessed. Full equipment identity is deferred to 12.0B.

For 12.0A, the Home Assistant host copies only immutable fields from the
repository's existing IntelliCenter protocol snapshot. It never retains or
passes the reference coordinator/controller into PoolOS, never reads HA entity
values for the native side, and never calls a command method. This is a
temporary transport feed behind the PoolOS-owned read-source seam; later stages
can replace it with a fully PoolOS-owned connection without changing canonical
mapping or parity.

The existing HA entity-derived `ObservationSnapshot` remains the sole
commissioning authority. Native mapping and parity execute afterward and are
stored in separate shadow-only coordinator fields. Native evidence is not
passed to observation health, the latch, durable observation recording,
behavioral inference, retrospectives, soak quality, solar learning, multiday
commissioning, recommendations, decisions, execution, or delivery.

## Comparison policy

Parity uses exact equality for booleans and other nonnumeric values. Initial
absolute numeric tolerances are conservative commissioning defaults:

- temperatures: `0.5 °F`;
- pump speed: `25 rpm`;
- pump flow: `1 gpm`; and
- pump power: `50 W`.

Evidence older than five minutes relative to explicit `generated_at` is stale.
Results distinguish match, value mismatch, type mismatch, missing native,
missing HA, stale native, and stale HA. The report identity and ordering are
deterministic for identical explicit inputs.

## Failure isolation and startup

Missing, disconnected, malformed, or failed native sources affect only native
status and parity. During PoolOS startup grace, an unavailable reference
snapshot is `INITIALIZING` and no parity alarm is published. It becomes
`UNAVAILABLE` after startup without changing HA-source observation health or
commissioning quality.

## Safety boundary

The new PoolOS adapter has no connect, write, set, toggle, send, control,
dispatcher, delivery, HA service, or entity interface. It cannot perform
physical actuation. The existing reference package may contain control code,
but 12.0A imports no controller into the PoolOS core and invokes none of it.

After 12.0A, authority remains NONE, command delivery remains disabled, and
physical Pentair delivery remains disabled.

## Consequences

PoolOS can measure native-versus-bridge parity before changing any source of
truth. Full native inventory, source selection, entity publication, dependency
removal, and any command path remain separate reviewed milestones.
