# Home Assistant stop task quiescence

## Baseline and live evidence

Reviewed v1.0.23 / main `62fc366889f5980f70506d6823ca33c1321debfc`, following
PRs #439 and #440. October 4 commissioning passed manual Pool circulation at
2600 RPM beyond the 120-second freshness boundary, clean manual Pool Off, and
external-user Spa operation/restart without BODY ownership reconstruction.
Manual Spa Off and Reset restored clean idle with filtration SATISFIED.

HA nevertheless logged an owned-pump reobservation task surviving final writes:

> 2026-10-04 05:37:33.458: PoolOS owned pump-session native reobservation was still running after final writes shutdown stage

The same warning occurred October 3 at 17:51:02.585, 16:19:02.603 and 15:18:24.935.
These commissioning reports establish the defect; no live HA/equipment access was
used for this repair.

## Root cause and HA event ordering

The registered STOP listener called only coordinator preparation. Automatic
runtime cancellation existed exclusively in config-entry unload. PoolOS therefore
had no integration-wide teardown at the earlier stop boundary. Config-entry
unload is not a prerequisite for final writes, and cannot serve as that boundary.

The upstream [HA core shutdown implementation](https://github.com/home-assistant/core/blob/dev/homeassistant/core.py)
fires STOP and awaits its listener work, then FINAL_WRITE, then CLOSE. Tasks
created before STOP with `hass.async_create_task` remain in the previously tracked
set: they are not automatically awaited merely because STOP fired. HA warns about
surviving tasks after final writes. This is source inspection of upstream HA,
not a claim about an independently measured installed HA version.

The red regression executes the actual entry STOP callback expression and the
production owned-pump loop. Against unmodified v1.0.23 it fails with:
`STOP left owned pump-session reobservation running`, at the same sleep boundary
as the physical warning. Cancellation is awaited, including coroutine finalizers.

## Shared command-free contract

`PoolOSIntegrationLifecycle` is shared by STOP and normal config-entry unload.
It serializes concurrent calls and completes teardown once per entry:

1. At HA STOP, freeze only the existing exportable verified quick-restart
   checkpoint, retaining its exact receipts, generation and original age.
2. Without yielding, fence coordinator publication/scheduling, detach thermal
   observers, deny new manual transport delivery, and fence all automatic runtime
   drivers. No shutdown command is constructed or delivered.
3. Cancel/await runtime reobservation and auxiliary work. A command already inside
   dispatch may settle its existing receipt; no dependent successor may dispatch.
4. Discard in-memory orchestration authority, drain coordinator observation and
   analysis, and disconnect manual and read-only transports.
5. Later config-entry unload performs platform cleanup without repeating stop.

The frozen checkpoint is solely final-write persistence data. It neither grants
shutdown authority nor changes restore eligibility. User Spa, pending/unverified
sessions and other ineligible checkpoints still export no checkpoint. New runtime
composition remains unowned until the unchanged v1.0.23 restore contract admits
fresh evidence; equality alone cannot restore authority. Ordinary reload does not
freeze a shutdown checkpoint.

## Complete task/timer audit

| Owner | Work | Stop disposition |
| --- | --- | --- |
| Thermal automatic | owned-pump, cleanup, verification, Spa startup, shared-hydraulic rereads; restart evidence preparation | Existing cancellation now reached at STOP; cancel and await |
| Thermal automatic | execution epoch | Driver/final gateway fenced first; settle dispatched receipt; no new operation |
| Thermal automatic | restart-origin reevaluation | Auxiliary owner cancels/awaits and rejects late scheduling |
| Filtration automatic | owned keepalive, verification reread | Same early fence and cancellation/drain |
| Filtration automatic | execution epoch | Fence driver before first await; settle existing dispatch |
| Grid outage | execution epoch, pending frame | Synchronous authority fence, clear pending work, await existing dispatch; no stop-driven reduction |
| Sanitation | execution, persistence, post-delivery refresh | Fence authority, cancel/await auxiliary work, settle dispatch, persist durable remaining work |
| Coordinator | observation lock, analysis executor, native refresh, deferred start | Fence listeners and dirty queues; finish current observation/analysis; cancel/await native refresh/start |
| Reset entity | post-Reset refresh | Coordinator auxiliary owner; stop guard prevents late Reset closure |
| Feature switches | parent-loss safety-interlock task | Coordinator task owner awaits dispatched safety work; queued dispatch rechecks stopped transport inside lock |
| Light entity | transition timer | HA cancellable `async_call_later`, canceled by HA stop/entity removal; only updates entity state |
| Read-only transport | reconciliation, body metadata rereads | Existing task sets canceled/awaited by transport stop |
| Both transport handlers | reconnect starter, disconnect debounce | Shared awaited handler fence prevents new reconnect scheduling |
| Both controllers | native connection/keepalive | Await public controller stop/disconnect after handler tasks settle |
| HA framework | coordinator interval/debouncer, entity/service jobs | HA-owned timers/work; integration scheduling/manual final dispatch fenced; platforms removed on unload |

The pinned pyintellicenter 0.1.20 handler's synchronous `stop()` dropped canceled
reconnect/debounce handles and spawned a fire-and-forget controller stop. The
shared `async_quiesce_connection_handler` uses the same stopped flag and cancelled
task fields, awaits cancellation, and leaves disconnect to the already-awaited
owning transport. It avoids spawning an unowned disconnect task. These private
fields are a pinned dependency contract; review them on dependency upgrades.

Purpose transitions previously canceled a reread and immediately cleared its
current-task field. A cancelling task could therefore escape later unload while
unwinding a read. The second red regression reproduces that gap. All noncritical
thermal/filtration tasks now remain registered until finished, including tasks
from previous purposes. STOP awaits them and does not recancel a coroutine
already unwinding cancellation.

## Preserved invariants and validation

No arbitration batch, freshness interval, topology admission, thermal/filtration
policy, BODY/PUMP/THERMAL attribution, manual RPM scope, source selection, restart
checkpoint eligibility or Reset accounting rule changes. Stop fabricates neither
operator intent nor command provenance. BODY Off requests after stop are denied
before restraint callbacks. Queued requests are denied inside the dispatch lock
without being mislabeled uncertain delivery. Dispatched results remain truthful.

New regressions cover actual STOP registration, active pump loop, all six thermal
reread/preparation fields, auxiliary finalizers, filtration keepalive/verification,
coordinator scheduling, late entry unload, handler tasks, exact Spa checkpoint
preservation versus external Spa, and command-lock races. Existing native
arbitration, Pool shutdown/reacquisition, external Spa, quick-restart, manual RPM,
Reset and full repository tests remain required. Source-location assertions follow
teardown into the lifecycle module; no ownership/currentness expectation is weakened.

Physical confirmation after a separately approved release: restart HA during an
external Spa session and an eligible verified PoolOS-originated session; confirm
no shutdown-task warning, no stop-driven commands, unchanged session origin and
checkpoint restoration. Software tests do not prove physical disconnect latency.
No restart, deployment, release or equipment action is part of this repair.

Local validation of the final candidate: 232 focused tests, 3,866 full tests;
Ruff (including the custom integration and scripts), MyPy (224 source files),
compileall and `git diff --check` passed. Full pytest used an exact candidate
content copy to exclude an existing ignored `.DS_Store` from the strict
integration inventory test; that local file was not modified. The known duplicate
ZIP-member warning remained. Hosted CI must validate the published exact head.
