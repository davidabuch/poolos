# ADR-107: Maintenance authority and native-change attribution

## Status

Accepted for command-boundary and command-free diagnostic foundations. Broad
automatic reconciliation remains disabled.

## Context

PoolOS has one commissioned Home Assistant mutation gateway for Pool/Spa body
state, targets, heat sources, IntelliChlor outputs, selected accessory circuits,
Pool Light effects, and the commissioned Pool PMPCIRC setpoint. Thermal live
delivery also uses that gateway. The independent IntelliCenter connection is
read-only and remains authoritative for observed native truth.

PoolOS needs a global maintenance interlock and a way to distinguish a native
transition that matches a recent PoolOS command from a transition with no
PoolOS correlation. Correlation is attribution evidence, not proof of the
external actor: another actor could theoretically make the same change at the
same time.

## Decision

### Central physical authority

Every current PoolOS physical mutation passes through
`ManualIntelliCenterControl`. The gateway performs a preliminary central
authority assessment, reserves a typed expected native consequence, waits for
its existing command lock, and performs a final authority assessment
immediately before invoking the pyintellicenter dispatch coroutine.

This dispatch interlock composes with, rather than replaces, the existing core
`ControlAuthority`: the latter resolves proposal/source ownership, while the
physical gateway provides the final global maintenance and controller-mode
deny plus native-consequence attribution for the commissioned HA transport.

The authority decision is fail-closed. It denies while persisted maintenance
state is unresolved, while PoolOS Maintenance Mode is on, and while native
controller mode is unresolved, Service, or Timeout. Maintenance denial applies
equally to manual, autonomous, reconciliation, and safety-interlock request
sources. It does not weaken IntelliCenter hardware protections or the distinct
Thermal Live Execution gates.

If Maintenance turns on while a request waits for the command lock, final
authorization fails and no dispatch begins. A network operation that already
began may finish; PoolOS does not attempt unsafe transport cancellation.

### Maintenance Mode

`switch.poolos_maintenance_mode` is a persistent global physical-command deny.
Home Assistant restore resolves its state, but the central authority starts in
an unresolved/denied state so there is no transient permissive startup window.
The first installation resolves to off when no prior state exists. Restored on
remains on. Pending expectations are never persisted.

Maintenance Mode does not stop observation, native publication, parity,
commissioning evidence, or diagnostics. Turning it off only removes the global
deny: it does not enable Thermal Live Execution, replay commands, restore a
pre-maintenance equipment snapshot, or dispatch reconciliation. Current native
truth becomes a fresh prospective comparison baseline.

### Expected native consequences

Expectations are registered before a command waits for delivery. They are
concept-, object-, and value-specific, bounded to 64 entries and 45 seconds,
and inactive until final dispatch begins. Final denial or delivery failure
removes the expectation. Accepted dispatch retains it until matching
authoritative native evidence consumes it or it expires. Expectations never
optimistically mutate native state and are invalidated on maintenance changes
and restart.

Before reserving a transition expectation, the gateway compares the requested
consequence with the latest authoritative native truth. A true no-op may still
be dispatched for manual API compatibility, but it retains no transition
expectation. The configured Pool PMPCIRC `p0102` `SPEED` consequence is mapped
separately from parent-pump actual RPM; configured setpoint and physical speed
are never treated as the same fact.

### External/unattributed changes

The native snapshot callback compares accepted chronological snapshots only.
Startup, reconnect/discovery generation changes, reload, and maintenance exit
establish fresh baselines. Duplicate or regressive evidence does not produce an
external event. A matching dispatched expectation is classified as a
correlated PoolOS consequence; other accepted transitions are
external/unattributed native changes.

The stable Home Assistant event is `poolos_external_change`. Its bounded fields
include concept, semantic event type, native object ID, before/after values,
time, maintenance status, policy, action, notification
recommendation, reconciliation requirement, intended value, reason code, and
changed semantic fields. No mobile notifier is embedded. The Control Center
retains counters, current drift concepts, and only the latest bounded event—not
an event history.

### Product policy

Policy and notification are independent:

| Concept | Policy | Notify |
| --- | --- | --- |
| Pool active | ACCEPT | yes |
| Spa active | ACCEPT | no |
| Pool target | ADOPT | yes |
| Spa target | ADOPT | no |
| IntelliChlor Pool/Spa output | ADOPT | yes |
| Pool Light state/effect, Jets, Slide, Spillway | ACCEPT | no |
| Freeze, system mode, firmware | OBSERVE | yes |
| Pool/Spa native heat source under explicit thermal ownership | RECONCILE | yes |
| Pump RPM under an explicit current RPM requirement | RECONCILE | yes |
| Unowned RPM or heat-source state | ACCEPT | no |
| Native schedule create/change/delete | OBSERVE | yes |

Active drift is recomputed from current native truth and the current usable
thermal ownership context on every accepted snapshot. Losing ownership,
entering Maintenance, reconnecting, or changing the intended value cannot
leave historical drift latched. Blocked or unusable thermal plans claim no
ownership; incompatible simultaneous pump requirements fail closed as
unowned.

Configured BODY heat-mode ownership is distinct from the momentary thermal
operating decision. After requested-mode restoration is resolved and a usable
authoritative BODY `HEATER` baseline exists, direct requested modes map to
configured intent as Off=`00000`, Gas=`H0001`, and Solar=`H0002`, regardless of
body activity or the planner's current selected source. For example, requested
Pool Solar with native `HEATER=H0002`, a collector below the minimum, and
`planned_source=off` is configured correctly: PoolOS simply does not apply
solar heat at that moment, and no configured heat-mode drift exists.

PoolOS Solar Preferred remains policy intent and has no static direct native
`HEATER` mapping. Operational pump-RPM ownership continues to require a usable
thermal assessment, active body, technical preflight, and an unambiguous RPM
claim. Thus persistent configured-source intent and current operational pump
requirements cannot redefine one another.

RECONCILE means current drift/reconciliation-needed evidence only. This ADR
does not authorize physical correction. ADOPT uses authoritative native truth
and existing requested-state mechanisms where they exist; it does not create a
second configuration database. External Pool off does not erase the separate
filtration obligation ledger.

PoolOS Solar Preferred remains distinct from Pentair Solar Preferred.
Repository/native mapping proves Pentair represents Solar Preferred as a HEATER
object with subtype `SOLARPREF` selected by a BODY `HEATER` reference. It is
observable conflict evidence and is never emitted as HXSLR or written through
the commissioned manual heater allow-list.

### Schedule lifecycle

Known `SCHED` objects are monitored through the existing native model. A known
schedule modification is observable. Deletion is conservatively recognized as
the commissioned tombstone/reset signature (X circuit, OFF, zero start/stop
times, zero update date, and the observed reset LOTMP value 78), not merely
object disappearance, and produces one
semantic deletion event. Reuse of a known tombstoned slot is classified as one
creation event. Snapshot absence alone produces no deletion claim.

Ordinary NotifyList updates do not insert a previously unseen schedule ID;
fresh discovery did so in commissioning. Whether a known tombstoned SCH slot is
always reused is unproven. This change therefore adds no config-entry reload,
restart, second connection, recurring discovery, or polling. It also does not
alter BODY/SENSE RequestParamList contracts. A bounded read-only discovery
primitive may be evaluated later if live evidence proves it necessary.

## Consequences

- Maintenance is enforced at one current production delivery gateway rather
  than scattered entity checks.
- Existing entity unique IDs and manual-control semantics remain stable.
- External events and active drift are distinct; accepted/adopted events do not
  become permanent drift flags.
- No schedule, filtration, chemistry, thermal, or accessory reconciliation is
  automatically delivered by this foundation.
- No new socket, command transport, polling loop, sleep-based confirmation, or
  Home Assistant service call is introduced.
- Native Service and Timeout modes deliberately deny both manual and autonomous
  PoolOS writes so PoolOS cannot fight a technician or the local controller.
  Returning to Auto only permits fresh requests; nothing denied or queued in a
  prior controller mode is replayed.
- During Maintenance, parent-loss safety interlocks remain diagnostic and do
  not bypass the global deny. Repeated native publications do not repeatedly
  schedule doomed writes; leaving Maintenance reevaluates fresh native truth.
