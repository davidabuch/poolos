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

## Multi-day commissioning intelligence

Milestone 11.6 aggregates only completed canonical daily retrospectives across a
caller-supplied inclusive date range. It does not reread raw observation logs or
reinterpret daily quality. `GOOD` days form the clean evidence base;
`DEGRADED` and `EXCLUDED` days remain visible in provenance but contribute no
clean cross-day solar samples.

The default commissioning gate requires 5 `GOOD` days, 3 consecutive `GOOD`
days, 3 clean usable solar-learning days, 5 complete solar episodes, and no
incident in the most recent 2 reporting dates. Missing reports, open/recent
incidents, or a period dominated by `DEGRADED` and `EXCLUDED` days requires
engineering review. These values are conservative commissioning defaults, not
scientifically validated thresholds.

`SUFFICIENT_FOR_POLICY_REVIEW` allows only human review of empirical evidence. It
does not choose a solar differential, create a controller rule, change PoolOS
policy, increase authority, or enable actuation. Observed Pentair behavior is not
necessarily optimal behavior.

Home Assistant publishes a rolling report over at most 14 completed local days.
The coordinator reconstructs canonical daily reports in its existing executor
workflow; the multi-day core consumes only those reports and never a current
partial day.

## Expected-outage operator annotation

Milestone 11.6.1 adds an observation-only dashboard button for known Pentair or
IntelliCenter interruptions. Pressing it at `T` durably records a matching
window from `T - 2 hours` through `T + 2 hours`. It can match an outage
acknowledged before, during, or after it occurred, including across local
midnight. The matching window is not the outage duration.

Raw health remains truthful and live `UNHEALTHY` alerts are never suppressed.
The incident retains its actual start, end, duration, unavailable or stale
observations, and source IDs. A match adds `EXPECTED_OUTAGE`,
`OPERATOR_ACKNOWLEDGED`, acknowledgment provenance, and
`troubleshooting_required: false`.

Expected incidents remain visible but do not count as unexplained commissioning
reliability incidents. Evidence inside the actual outage remains unavailable
and is excluded from solar learning; independent coverage or evidence gaps may
still lower daily quality. The button cannot reset health, restart Pentair, call
equipment services, change policy, or increase authority.
