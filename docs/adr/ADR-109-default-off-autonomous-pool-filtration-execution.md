# ADR-109: Default-off autonomous Pool filtration execution

## Status

Accepted

## Context

ADR-106 deliberately keeps filtration accounting and scheduling command-free.
It produces the authoritative obligation, disposition, and ordinary filtration
RPM, but it does not answer how a physical Pool circulation session is safely
created, transferred to thermal work, resumed after thermal work, or ended.
Treating an already-running Pool as owned would violate PoolOS provenance and
external-change safety rules.

## Decision

PoolOS uses a separate, default-off **Automatic Filtration Execution** driver.
The driver consumes the existing filtration assessment; it does not reproduce
TOU, debt, temperature, or credit policy. Enabling the driver requires a newer
authoritative observation epoch, and restart/reload resets effective authority
Off.

The commissioned physical envelope is Pool-only:

- activate or deactivate Pool body `B1101`;
- write the dynamically discovered Pool `PMPCIRC` object to the canonical
  ordinary-filtration target (currently 2600 RPM).

Every request is bound to one current observation epoch, driver session,
operation identity, exact target, and exact typed value. The central physical
gateway rechecks this binding immediately before transport invocation.
`StopPump`, `SetHydraulicRoute`, generic circuit control, Spa control, and
arbitrary RPM writes remain unauthorized.

Accepted delivery records bounded in-memory provenance, but full filtration
ownership is established only after a later authoritative observation verifies
both Pool body activation and the exact configured plus tolerant actual pump
state. Hardware equality alone never creates provenance. Ownership is not
persisted and is cleared on unload, restart, positive external takeover,
incompatible topology, verification failure, or dynamic `PMPCIRC` identity
change.

A verified filtration lease is suspended, rather than discarded, when current
required observations are temporarily unusable. Suspension permits no new
delivery or thermal handoff. It retains only the exact in-memory session,
generation, body receipt, and pump receipt needed to resume after current state
is reverified or to perform the already-authorized Pool body cleanup. There is
no evidence-loss timer: repeated unusable epochs remain command-free and expose
operator-review diagnostics. A usable Pool-Off observation releases the lease
without a redundant command. Positive external takeover, conflicting topology,
or a changed dynamic `PMPCIRC` identity still invalidates the lease immediately.

One shared Pool circulation registry arbitrates the filtration and thermal
drivers. Thermal reserves an actionable Pool candidate synchronously before
either asynchronous driver may deliver in that epoch. A thermal driver latched
pending operator re-enable cannot reserve an epoch: the existing filtration owner
must remain able to perform its own current work or provenance-bound cleanup.
A terminal thermal lease with no active session, in-flight delivery, residual
termination entitlement, or cleanup provenance releases only its matching registry
claim during synchronous arbitration. Failed reduction work therefore cannot
exclude a later independently authorized filtration session indefinitely.
A verified filtration
lease may transfer only its proven body-activation provenance to thermal; the
2600-RPM provenance is not compatible with Solar or Gas and must be replaced by
a freshly accepted thermal pump operation. Conversely, verified thermal cleanup
normalization may establish a filtration lease only from retained body
provenance and the newly accepted, later-verified canonical filtration pump
operation. Neither handoff is inferred from observed state.

When filtration is no longer immediately required and no thermal successor is
reserved, the filtration driver may request Pool body Off only from its own
current body-activation provenance. Disabling the operator gate prevents new
work; a later fresh epoch may perform this same narrowly bound owned cleanup.
Uncertain ownership causes fail-closed relinquishment, not cleanup of external
circulation.

## Safety and operational consequences

- Accounting remains the sole scheduling and credit authority. Actual observed
  Pool-routed RPM continues to determine filtration credit.
- `DEFERRED_TOU` and `DEFERRED_OPTIMIZATION` do not create execution work;
  `RUN_NOW` and already-valid `CREDITING` are immediate dispositions.
- Spa activity or other positive topology conflict, changed dynamic pump
  identity, physical-authority denial, non-confirmed on-grid state, or relevant
  external change preempts. Temporarily unavailable required evidence suspends
  an already-verified lease but cannot create one.
- Delivery is event-driven by authoritative observation epochs. No polling,
  sleeps, retry timers, ownership persistence, or alternate transport exists.
- Filtration and thermal cannot independently command Pool circulation in the
  same epoch. Handoffs are explicit, typed, and provenance-bound.
- Hot Tub autonomy and Grid Outage Physical Safety remain separate and retain
  their existing default-off authority boundaries.
