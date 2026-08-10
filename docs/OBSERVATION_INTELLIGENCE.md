# Observation Intelligence and Soak Quality

PoolOS milestone 11.5 turns existing durable observation history into
deterministic daily engineering evidence. It does not add equipment control.

## Daily quality

Every `DailyOperationalRetrospective` includes `soak_quality` with one status:

- `GOOD`: coverage and health meet the conservative daily gates and no incident
  or other degrading limitation is present. Startup provenance alone does not
  degrade an otherwise good reporting window.
- `DEGRADED`: evidence remains visible but must be reviewed before it contributes
  to cross-day learning.
- `EXCLUDED`: evidence is too incomplete or unhealthy for behavioral-learning
  conclusions.

The exact gates and their rationale are defined in ADR-088. They are initial
engineering thresholds, not scientifically validated constants.

## Observation incidents

An incident groups consecutive durable evidence for missing, unavailable, stale,
or unhealthy upstream observations when canonical `health.healthy` is false.
That canonical flag already incorporates the live observation bridge's
context-aware freshness rules. A healthy record may therefore retain raw
`stale_entities` metadata without representing an operational failure, and the
retrospective must not reinterpret that tolerated metadata as an incident or
degraded stale duration. The generic domain model does not assume
that every incident is an IntelliCenter or network failure. A later healthy event
closes the incident and proves recovery; otherwise the incident remains open.
Recovery never deletes the incident or its source-event provenance.

Each durable `baseline` begins a deterministic 60-second retrospective startup
grace interval, matching live commissioning health behavior. Unhealthy,
unavailable, or stale initialization evidence remains in raw provenance during
that interval but does not create an incident or degradation duration. If
supported unhealthy evidence continues beyond the grace boundary, a normal
incident begins at the boundary. A baseline is evidence of startup behavior; it
does not prove whether the cause was a Home Assistant restart, integration
reload, first installation, or another initialization event.

## Solar learning

Solar activations and deactivations are inferred only by the canonical behavioral
inference engine. Available thermal, hydraulic, equipment, demand, preference,
and time-offset context is attached to each transition. Activations are paired
with later deactivations; unmatched activations remain open.

Daily solar summaries report empirical transition and episode evidence. Medians
require at least two available samples, missing values are not fabricated, and
provisional hysteresis is never represented as a PoolOS control rule. Excluded
days are unusable for conclusions; degraded days remain visible with an explicit
review limitation.

## Read-only operation

Observation intelligence consumes durable evidence and produces typed reports,
JSON/CSV exports, diagnostics, and read-only Home Assistant publication. It
contains no service call, command, equipment write, automatic actuation retry,
vendor operation, or authority increase.
