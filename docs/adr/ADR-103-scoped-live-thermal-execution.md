# ADR-103: Scoped Live Thermal Execution

Status: accepted

## Context

ADR-102 created command-disabled coupled Pool/Hot Tub plans containing only
`SetPumpSpeed` and `SetHeatMode`. PoolOS's general execution authorization
correctly rejects LIVE runtime and physical endpoints. Removing those global
guards would grant authority far beyond thermal commissioning.

The commissioned stable identities are Pool circuit `C0006`, Pool body `B1101`,
Hot Tub body `B1202`, Off `00000`, Gas `H0001`, and Solar `H0002`. IntelliCenter
may recycle the concrete `p01xx` PMPCIRC object representing the Pool circuit's
RPM assignment, so the current native target must be uniquely resolved from
`PMPCIRC + CIRCUIT=C0006 + SELECT=RPM + valid PUMP parent`. Phase 2 must provide
a production-capable path without activating it, changing hydraulic routes,
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

Normal thermal authority admits only `SetBodyActive(Pool/Hot Tub, True)`,
`SetPumpSpeed(current Pool C0006 PMPCIRC,
solar_heating_rpm/gas_heating_rpm/priming_rpm)`, and body-matching
`SetHeatMode(Off/Solar/Gas)`. Body activation
requires both body observations to be fresh and usable, the target to be
explicitly inactive, the other body to be explicitly inactive, and no separate
hydraulic veto. Body deactivation remains prohibited. Filtration, probe,
grid-outage, and Spillway RPM values are not thermal authority even when
numerically equal.
Solar is blocked by native Solar Preferred, Solar RPM, or general RPM ownership
conflicts. Gas is blocked by native Gas/Heater/Spa RPM or general RPM ownership
conflicts. Native configuration is never rewritten.

Pool water-temperature acquisition has a separate, narrower authority purpose.
It admits only the exact operations in the current canonical Pool probe plan:
exact Pool `HEATER=00000` preconditioning followed by Pool body activation when
needed and the exact discovered Pool `PMPCIRC` semantic acquisition setpoint of
1500 RPM. Source Off is an owned
configuration mutation, is verified from exact raw native HEATER truth, and is
available only from a step carrying the canonical probe-source-precondition
marker and exact `pool.raw_heater_id=00000` consequence. Every operation remains
bound to the canonical probe reason, plan/step metadata, execution-purpose
identity, current epoch, and exact target/value. No arbitrary Off-source
circulation, Hot Tub operation, or Gas/Solar source selection
can use this envelope. Final matching is type-exact so
boolean/integer equality cannot widen the boundary.

Accepted body activation is not acquisition. Later authoritative evidence
must prove Pool active, Spa inactive, complete inactive shared hydraulics,
authoritatively on-grid state, the configured semantic Pool `PMPCIRC` setpoint
at exactly 1500 RPM, and actual pump RPM within the commissioned analog
tolerance of 1500. The bounded fallback order is source Off, Pool body On, then
the 1500-RPM setpoint; it does not synthesize a native 3000-RPM priming phase.
Acquisition timing begins only after both configured and physical RPM evidence
verify in a later authoritative frame. Only then does one in-memory acquisition
epoch start.

The command-free water-temperature tracker remains the policy authority for the
two-minute minimum acquisition, one-minute stability window, 2 F/minute smooth-
rate limit, five-minute fail-closed maximum, and current-operational-day retained
bulk-water reference. Samples are authoritative, chronological, bounded,
strictly later than the acquisition boundary, and never combined across a
topology, shared-hydraulic, grid, external-takeover, currentness, or ownership
break. Matching hardware without accepted PoolOS provenance cannot start or
restore an acquisition.

The Pool operational day is the filtration day, 08:00 local through the next
08:00. A successful acquisition retains its trusted bulk-water value in memory
for that operational day so later Pool-off Solar opportunities do not repeatedly
reactivate circulation. The retained reference is invalidated on restart,
operational-day rollover, or Spa routing; fresh trustworthy Pool circulation
supersedes it. With Pool inactive, a retained-reference Solar trial requires
collector temperature at least 90 F and differential at least 7 F. Once the Pool
is circulating, fresh water evidence governs: differential 6 F or higher
continues, 5 F or lower aborts, and the already-started trial remains active in
the bounded 5-to-6 F hysteresis band.

Probe success publishes canonical trusted water evidence only. A fresh normal
thermal evaluation independently selects Solar, Gas fallback, Off, or no eligible
source under all normal gates. Probe authority cannot authorize the successor.
For the exact same-mode Pool probe successor, an explicit typed handoff may retain
only accepted Pool body-activation provenance. It discards the probe pump/source
provenance before a newly authorized 2900-RPM Solar or 3000-RPM Gas operation and
reacquires each concept only from a fresh accepted delivery. State equality never
performs this handoff. Incompatible, stale, cross-body, or externally preempted
successors use the established relinquishment/cleanup path; it never restores a
remembered RPM or turns off a pre-existing body.

Solar policy separately represents a favorable pre-circulation opportunity,
native Solar configuration, actual IntelliCenter Solar engagement, and active
Solar continuation. A Pool-inactive state does not by itself veto a favorable
opportunity. Exact raw Pool `HEATER=H0002` verifies source configuration even when
`solar.active` remains false; only IntelliCenter decides whether collectors
actually engage. For PoolOS-started Solar circulation, a five-minute in-memory
effectiveness window observes `solar.active`, with a 30-second continuous
confirmation hold. Missing or unusable engagement evidence remains unknown before
that absolute deadline and resets the continuous confirmation hold; it does not
invalidate the already-verified H0002 configuration. Non-engagement is an
operational disposition, not failed H0002 verification: the existing
provenance-bound source-Off and filtration-aware cleanup lifecycle runs, and the
unchanged opportunity is suppressed for 30 minutes. These constants are isolated
policy defaults and add no retry loop, scheduler, persistence, or generic stop
authority.

Optional shared-hydraulic circuits are inventory states rather than mandatory
installation assumptions. Only an immutable snapshot explicitly marked complete
after successful native all-equipment discovery may prove Waterfall, Jets, or
Slide authoritatively absent; core-object presence is not a completeness signal.
Installed-and-Off is safe; installed but missing, stale, or unusable remains
blocked; unknown inventory completeness cannot imply Off.

Command-free candidate admission evaluates native body and shared-hydraulic
evidence over a bounded 120-second currentness window. This is derived from the
independent native transport's 90-second keepalive/read cadence plus one
30-second coordinator reconciliation/scheduling interval; it is not permission
to retain stale state indefinitely. Evidence older than that bound, missing,
non-LIVE, low-confidence, unusable, contradictory, or active still blocks.
Active ownership, probe acquisition continuity, and post-delivery verification
retain their stricter 30-second freshness contract and require later
authoritative epochs.

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
for the exact current Pool `C0006` PMPCIRC RPM target and commissioned body
`HEATER` selection only. This adapter
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
with a distinct typed termination purpose. The final boundary admits only the
provenance-bound target body `body_heat_source=00000` for that purpose; body
activation/deactivation, Gas, Solar, RPM changes, routing, and pump stop are
rejected. Thermal Live,
commissioning scope, Maintenance, controller mode, authoritative epoch, and
unload checks still apply. The normal automatic gate does not become a cleanup
bypass: while it is Off no termination command is scheduled. An accepted Off
receipt waits for a later authoritative `HEATER=00000` observation, and no
subsequent action or retry is chained in the same epoch.

After authoritative Pool source-Off confirmation, the driver may retain a
separate, in-memory circulation-cleanup provenance copied only from accepted
body-activation and pump-setpoint provenance. A fresh canonical circulation-
successor assessment may bind one exact Pool body-Off candidate, or one exact
current Pool PMPCIRC filtration-successor RPM candidate, to the current
authoritative epoch.
These use distinct typed final-gateway purposes; neither extends normal thermal
authority. Body-Off requires accepted PoolOS body-activation provenance. Pump
normalization requires accepted pump-setpoint provenance and the exact current
canonical filtration target. Accepted delivery waits for a later authoritative
native consequence. Verified pump normalization consumes the pump cleanup
capability, so later target changes cannot create repeated filtration control;
independent body provenance may remain until filtration ceases to be an
immediate successor. Restart, unload, gate loss, or external/hydraulic takeover
discards cleanup provenance without a compensating command.

A separate persistent human-Off restraint prevents automatic Pool control from
undoing an operator's deliberate Pool-Off action. A Pool Off requested through
PoolOS manual control arms the restraint synchronously before delivery; an
uncorrelated authoritative native Pool On-to-Off transition also arms it.
Baseline Off and a correlated PoolOS cleanup consequence do not. While armed,
the final gateway independently denies automatic Pool thermal, filtration, and
grid-outage mutations, while manual commands remain subject to their ordinary
authority checks. Active automatic work is preempted without retry. A verified
filtration session may retain only its exact existing cleanup provenance while
evidence is unavailable; the restraint never manufactures ownership from
matching hardware.

The Home Assistant restraint entity restores only the latched restraint across
restart. It never restores a session, expectation, receipt, or ownership lease.
Explicit Resume is command-free and merely permits a later fresh evaluation;
it does not replay prior work. A controller-side Off that happens while PoolOS
and Home Assistant are offline cannot be distinguished from baseline Off after
restart, so that case remains an explicit operator-review limitation.

The generic Pentair physical endpoint independently rejects `pump.set_speed`
unless its target exactly matches the Pool PMPCIRC identity bound into that
endpoint, its sole parameter is an integer `rpm`, and the value is the
commissioned 2900 or 3000 thermal baseline. Existing body/heater endpoint bounds
remain unchanged.

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
- No authority is granted to `StartPump`, `StopPump`, `SetHydraulicRoute`,
  arbitrary body deactivation, arbitrary circuits or vendor commands,
  Spillway, generic filtration execution, Hot Tub probing, grid outage, lighting,
  chemistry, schedules, or configuration changes. Body deactivation exists only
  as provenance-bound cleanup after Pool thermal purpose or a PoolOS-owned
  opportunistic Spa purpose ends; externally started Spa remains ineligible.
- Inactive-body manual configuration remains available. Autonomous inactive-Spa
  `HEATER` preselection is admitted only for a PoolOS opportunistic plan, only
  as exact Solar or Off, and only before provenance-bound Spa activation while
  Pool is authoritatively inactive.
- Pool temperature-acquisition authority is limited to the provenance-bound,
  pump-write-free envelope above. Hot Tub temperature acquisition has no
  automatic fixed RPM unless a separately commissioned runtime purpose requires
  one. Physical outage response remains
  separate work. Source termination remains ownership-scoped exact body source
  Off; post-source circulation cleanup is separately provenance- and epoch-bound.

## Hot Tub execution-governance foundation

Hot Tub runtime uses a separately resolved, generation-current `PMPCIRC` whose
native circuit is Spa `C0001`; it never inherits the Pool `C0006` identity.
Configured `PMPCIRC.SPEED` and physical parent-pump RPM are separate required
verification facts. The commissioned purpose baselines remain body-neutral:
1500 temperature acquisition, 2600 ordinary circulation, 2900 actively engaged
Solar, and 3000 actively firing Gas. Selected `HEATER=H0001/H0002` remains exact source
configuration truth, but does not by itself establish active heat delivery.

An externally started Spa remains externally body-owned. PoolOS may establish
only pump/source provenance through its own accepted commands and later native
verification; it cannot acquire body-Off authority from `spa.active=True` or
matching RPM. A PoolOS opportunistic Spa session is distinct and exists only
after accepted B1202 activation provenance. That in-memory session kind is not
restored. Source Solar/Off is verified while the Spa is still inactive before
an opportunistic activation, preventing a retained Gas selection from firing
during startup. Gas is never selected by opportunistic policy.

Exact Spa source-Off termination and B1202-Off cleanup are separate typed
gateway purposes. Spa deactivation is available only from retained accepted
PoolOS B1202 activation provenance and must be verified by a later authoritative
Spa-Off observation. It grants no pump stop, route operation, arbitrary RPM, or
right to deactivate an externally started Spa. Spa temperature evaluation is
command-free: inactive or ambiguously routed Spa temperature is not trusted. A
current native Spa temperature is usable only after a later frame proves Spa
exclusively active and actual RPM positive; this never grants body ownership.
External Spa sessions first normalize no-heat circulation to 2600, then may
prepare 3000 before PoolOS selects Gas from trusted demand evidence.
