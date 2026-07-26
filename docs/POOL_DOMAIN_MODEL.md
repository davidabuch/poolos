# PoolOS Domain Model

PoolOS is a vendor-independent operating system for intelligent pool and spa control.

## Scope

PoolOS owns pool and spa behavior. External systems such as Home Assistant,
weather services, utility pricing, and batteries provide commands or context;
they are not managed as PoolOS equipment.

## Topology

An `Installation` contains one or more `PoolSystem` objects. A system can serve
one or more bodies of water and may use shared or dedicated equipment.

Equipment is associated with a hydraulic system, not permanently owned by one
body. This supports:

- combined pool/spa systems with one equipment pad;
- separate pool and spa equipment;
- pool-only or spa-only installations;
- multiple independent systems on one property.

## Bodies, routes, and features

A body is a physical volume of water. A hydraulic route describes suction,
return, valve positions, equipment requirements, and optional minimum flow or
RPM. A feature is a user-visible function such as a waterfall, slide, bubbler,
or cleaner.

PoolOS applications request outcomes such as `heat spa` or `run waterfall`.
They do not operate vendor circuits directly.

## Truth levels

Every observation records provenance and confidence:

1. **Measured** — directly reported by hardware.
2. **Calculated** — deterministic math over measured values.
3. **Learned** — inferred from runtime history.
4. **Predicted** — a future estimate.

Derived values include evidence and can be explained to users and applications.
A low-confidence estimate must never be presented as a direct measurement.
