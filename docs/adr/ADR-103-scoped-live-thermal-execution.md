# ADR-103: Scoped Live Thermal Execution

Status: accepted

## Context

ADR-102 created command-disabled coupled Pool/Hot Tub plans containing only
`SetPumpSpeed` and `SetHeatMode`. PoolOS's general execution authorization
correctly rejects LIVE runtime and physical endpoints. Removing those global
guards would grant authority far beyond thermal commissioning.

The commissioned thermal identities are PMPCIRC `p0102`, Pool `B1101`, Hot Tub
`B1202`, Off `00000`, Gas `H0001`, and Solar `H0002`. Phase 2 must provide a
production-capable path without activating it, changing hydraulic routes,
rewriting IntelliCenter configuration, or resuming work after restart. A later
cold-start extension added narrowly bounded activation of the selected body,
without granting route selection or body-deactivation authority.

## Decision

PoolOS adds a separate typed `ThermalLiveAuthorizationEngine`. The existing
general authorization engine remains simulator-only. Thermal live policy has
two independent default-deny gates: `thermal_live_execution_enabled=False` and
a commissioning scope of `disabled`. Initial commissioning may select exactly
Pool or Hot Tub, never both through one scope value.

Authorization consumes a concrete ADR-102 `ThermalExecutionPlanAssessment` and
explicit current safety evidence. Every step is re-authorized immediately
before delivery. Authorization requires:

- current evaluation and plan identities;
- a plan no older than the configured maximum age;
- available independent native observations and manual delivery transport;
- fresh, healthy, non-contradictory authoritative evidence;
- fresh, usable, unambiguous Pool and Hot Tub activity evidence;
- satisfied hydraulic safety context and either an active target body or a
  safe target-body activation step while both bodies are explicitly inactive;
- no interrupted execution awaiting fresh reevaluation;
- required post-command expectations; and
- no native configuration conflict affecting the selected thermal capability.

Only `SetBodyActive(Pool/Hot Tub, True)`,
`SetPumpSpeed(p0102, solar_heating_rpm/gas_heating_rpm/priming_rpm)`, and
body-matching `SetHeatMode(Off/Solar/Gas)` are admitted. Body activation
requires both body observations to be fresh and usable, the target to be
explicitly inactive, the other body to be explicitly inactive, and no separate
hydraulic veto. Body deactivation remains prohibited. Filtration, probe,
grid-outage, and Spillway RPM values are not thermal authority even when
numerically equal.
Solar is blocked by native Solar Preferred, Solar RPM, or general RPM ownership
conflicts. Gas is blocked by native Gas/Heater/Spa RPM or general RPM ownership
conflicts. Native configuration is never rewritten.

`ThermalLiveExecutionEngine` converts the authorized thermal assessment into
the existing immutable proposal/authorization/plan models and reuses the
existing coordinator, per-step state machine, verification engine, receipts,
outcomes, and optional execution flight recorder. It delivers one step and then
stops at `AWAITING_VERIFICATION`. Only authoritative native verification may
advance the coordinator. The next operation requires another explicit method
call and a new authorization evaluation; there is no loop that blindly
dispatches the plan.

Immediately before delivery, the current execution-step operation must retain
the Phase 1 operation identity and exactly equal its typed live derivative.
The fresh authorization must reference that same operation ID. Any identity or
payload difference blocks without calling the delivery port. Static future
step metadata records only that live authorization is required; the actual
per-step attempt, receipt correlation, verification, and outcome retain the
fresh authorization ID used for that one delivery.

Every thermal step carries an immutable target-body hydraulic-continuity
contract. Verification requires the target body active and the other body
inactive using fresh, usable authoritative activity evidence. Missing, stale,
ambiguous, or contradictory topology terminates the session. A topology break
during a verified priming hold invalidates that hold and requires a fresh plan
and session; hold time is never paused or resumed across the break.

Pump verification retains the inclusive 25-RPM tolerance and bounded settling
until the configured deadline. A fresh wrong `HEATER` fails immediately.
`HEATER` is the source truth; `HTMODE` is not written and is not required for
confirmation. Missing, stale, future, low-confidence, or unusable verification
evidence stops the execution.

The core defines an async thermal delivery port and imports no Home Assistant
code. The HA adapter wraps the existing `ManualIntelliCenterControl` methods
for `p0102` RPM and commissioned body `HEATER` selection only. This adapter is
explicitly validates Pool/Hot Tub and Off/Gas/Solar before mapping them to the
commissioned native IDs. Invalid values are rejected without calling manual
control. The adapter is not registered at startup and no runtime configuration
enables it in Phase 2. Manual controls remain separate.

The generic Pentair physical endpoint independently rejects `pump.set_speed`
unless its target is `p0102`, its sole parameter is an integer `rpm`, and the
value is the commissioned 2900 or 3000 thermal baseline. Existing body/heater
endpoint bounds remain unchanged.

## Safety consequences

- Kill switch and body scope default disabled; this commit cannot actuate by
  itself.
- Disabling the switch stops new steps and emits no restoration command.
- Pool and Hot Tub must already be active for source and RPM delivery. A
  cold-start plan may activate only its selected inactive body when the other
  body is explicitly inactive and all hydraulic evidence is usable. No route
  operation or body deactivation is inferred from configured mode or target.
- Newer evaluation or plan identity supersedes an in-progress plan before its
  next command. No automatic reversal is issued.
- Interrupted history cannot resume. Restart requires fresh observation,
  evaluation, authorization, and a newly begun session.
- Delivery rejection/failure/timeout, verification failure/timeout, stale
  evidence, unavailable transport, or a safety/configuration blocker stops the
  plan without retry.
- No authority is granted to `StartPump`, `StopPump`, `SetHydraulicRoute`, body
  deactivation, arbitrary circuits or vendor commands, Spillway, filtration,
  probing, grid outage, lighting, chemistry, schedules, or configuration
  changes.
- Inactive-body manual configuration remains available, but autonomous
  inactive-body `HEATER` preselection remains uncommissioned and prohibited.
