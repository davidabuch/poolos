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

Each live session retains three distinct identities: its concrete originating
evaluation, its concrete plan instance, and a stable execution-purpose identity
derived only from material body, requested-mode, selected-source, thermal-RPM,
target-temperature, and probe/Off semantics. The runtime supplies current typed
identity before delivery and verification. A new evaluation or residual plan may
continue only when the purpose is unchanged and its remaining operation structure
is a suffix explained by accepted or verified PoolOS session progress. Hardware
equivalence alone cannot explain progress. A purpose change, blocked plan,
unattributed convergence, or incompatible residual plan terminates the old
session before verification or coordinator advancement and discards any hold.

Currentness vocabulary is explicit:

- `evaluation_id` identifies one observation/evaluation epoch;
- `plan_id` identifies one concrete planner result;
- `execution_purpose_id` identifies the stable material objective;
- the residual plan is the currently required structural operation suffix;
- execution progress is only the accepted current operation and verified prefix
  retained by the live session;
- `SAME_PURPOSE` means a newer epoch retains the same objective and residual;
- `PROGRESS_COMPATIBLE` means PoolOS-attributed progress explains the shorter
  residual;
- `CONVERGED` means verified PoolOS progress explains a same-purpose empty plan;
- a material purpose change is true supersession, while unprovable structure is
  `UNKNOWN` and fails closed; and
- explicit runtime ownership handoff remains the separate ADR-108 mechanism.

Purpose compatibility never authorizes delivery and never replaces fresh safety
authorization or authoritative verification. Expected PoolOS delivery progress
may explain a shrinking residual, but a matching manual or external consequence
cannot. Although the deterministic purpose ID can be recomputed after restart,
sessions, receipts, verified progress, and ownership are in-memory and are never
restored from that match. The default-off automatic driver consumes this contract
rather than defining another equivalence algorithm.

Physical execution ownership is explicit accepted-delivery provenance scoped
to one in-memory session. An accepted session-bound body activation, pump
setpoint, or heat-source operation may establish the corresponding ownership;
matching native observations, pre-existing circulation, and externally caused
state never do. Ownership is cleared when the session completes or terminates
and is never persisted or reconstructed after restart. This provenance model
adds no command, RPM, body, or heat-source capability.

Pump verification retains the inclusive 25-RPM tolerance and bounded settling
until the configured deadline. A fresh wrong `HEATER` fails immediately.
`HEATER` is the source truth; `HTMODE` is not written and is not required for
confirmation. Missing, stale, future, low-confidence, or unusable verification
evidence stops the execution.

The core defines an async thermal delivery port and imports no Home Assistant
code. The HA adapter wraps the existing `ManualIntelliCenterControl` methods
for `p0102` RPM and commissioned body `HEATER` selection only. This adapter
explicitly validates Pool/Hot Tub and Off/Gas/Solar before mapping them to the
commissioned native IDs. Invalid values are rejected without calling manual
control. Manual controls remain separate.

The production automatic driver has its own non-restored, default-Off HA switch.
That gate does not replace the separate Thermal Live switch or one-body
commissioning scope: all three plus existing dynamic safety and final physical
authority are required. Enabling the driver never processes a cached candidate;
a later authoritative snapshot must independently pass every gate.

Before session creation, a command-free whole-plan structural preflight checks
every operation against the canonical live operation and step contracts. One
unsupported future operation rejects the plan before step zero. Static
eligibility never replaces per-step dynamic authorization. Each unique
authoritative snapshot may submit at most one new physical operation; a later
snapshot may verify the prior operation and submit at most one next operation.

The synchronous runtime callback uses at most one config-entry-owned one-shot
async task to bridge to delivery. It has no scheduler, polling loop, sleep,
retry worker, persistent queue, or restored session. Final physical authority
receives a typed context bound to driver generation, snapshot, session, and body.
Gate, scope, unload, or newer-snapshot changes invalidate that context, which is
rechecked inside the existing command lock immediately before transport.

Residual source de-selection reuses that same serialized task and final gateway
with a distinct typed termination purpose. The final boundary admits only Pool
`body_heat_source=00000` for that purpose; body activation/deactivation, Gas,
Solar, RPM changes, routing, and pump stop are rejected. Thermal Live,
commissioning scope, Maintenance, controller mode, authoritative epoch, and
unload checks still apply. The normal automatic gate does not become a cleanup
bypass: while it is Off no termination command is scheduled. An accepted Off
receipt waits for a later authoritative `HEATER=00000` observation, and no
subsequent action or retry is chained in the same epoch.

The generic Pentair physical endpoint independently rejects `pump.set_speed`
unless its target is `p0102`, its sole parameter is an integer `rpm`, and the
value is the commissioned 2900 or 3000 thermal baseline. Existing body/heater
endpoint bounds remain unchanged.

## Safety consequences

- Thermal Live, body scope, and the automatic-driver switch default disabled;
  startup cannot actuate by itself.
- Disabling the switch stops new steps and emits no restoration command.
- Pool and Hot Tub must already be active for source and RPM delivery. A
  cold-start plan may activate only its selected inactive body when the other
  body is explicitly inactive and all hydraulic evidence is usable. No route
  operation or body deactivation is inferred from configured mode or target.
- A materially newer purpose or unprovable residual plan supersedes an
  in-progress plan before its next command or verification. Mere timestamp-driven
  evaluation and plan-instance churn does not supersede a provably compatible
  purpose. No automatic reversal is issued.
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
- Temperature-probe plans remain wholly rejected because 1500 RPM is not
  commissioned thermal authority. Hot Tub automatic execution remains blocked
  pending body-specific configured-pump ownership evidence. Physical outage
  response and body/pump authority-loss cleanup remain separate work; the only
  termination operation is ownership-scoped Pool source Off.
