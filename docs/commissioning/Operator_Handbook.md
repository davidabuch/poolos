# PoolOS Operator Handbook

## What PoolOS Is

PoolOS is an evidence-driven operating system that observes, models, explains,
and optimizes pool and spa operation. It begins as an observer and gains authority
only when the operator explicitly approves it.

## Operating Modes

| Mode | What PoolOS may do | What PoolOS may not do |
|---|---|---|
| OBSERVE | Read, normalize, diagnose, and record | Recommend or command |
| LEARN | Derive inspectable operating characteristics | Recommend or command |
| ADVISE | Present recommendations and alternatives | Send commands |
| SHADOW | Build complete hypothetical execution plans | Deliver commands |
| ASSIST | Execute approved bounded capabilities | Control unapproved capabilities |
| CONTROL | Operate within approved policy and safety limits | Exceed configured authority |

## Why PoolOS Has Not Acted

Common reasons include:

- the current mode does not permit actuation;
- the capability is not armed;
- required evidence is missing, stale, unavailable, or contradictory;
- an external or manual owner currently has authority;
- a safety or policy gate blocked the action;
- PoolOS delivered a command but has not verified the physical result;
- the system requires operator intervention.

The dashboard and Flight Recorder should expose the exact reason.

## Eligibility Versus Activation

PoolOS may report that a higher mode is eligible. This means the technical
criteria are satisfied. It does not mean PoolOS changed modes.

Every increase in authority requires explicit operator approval. PoolOS may
automatically lower authority when safety or health requires it.

## Human Override

Manual operation remains authoritative within the safety model. PoolOS must not
fight an unexplained operator or equipment-panel change. It should observe the
change, classify ownership, and explain what it is doing.

Safety constraints may still stop an unsafe condition. Such intervention must be
visible and recorded.

## Returning to OBSERVE

Use the PoolOS operating-mode control to select `OBSERVE`. The rollback action
should immediately block new PoolOS commands while preserving observations,
diagnostics, and Flight Recorder evidence.

After rollback:

- confirm the displayed current mode is `OBSERVE`;
- confirm PoolOS owns no active equipment capability;
- verify the native controller or manual controls remain available;
- review the recorded reason for rollback before rearming.

## Understanding a Recommendation

A recommendation should answer:

- What is PoolOS proposing?
- Why now?
- Which observations and policies support it?
- What assumptions were made?
- What alternatives were considered?
- What outcome is expected?
- How fresh and reliable is the evidence?

Do not approve a recommendation that cannot answer these questions.

## Understanding Command Status

PoolOS separates command delivery from physical success:

1. **Delivered:** Home Assistant accepted the service call.
2. **Observed:** relevant state evidence arrived.
3. **Verified:** observed state matches the expectation.
4. **Reconciled:** PoolOS determined what should happen next.
5. **Recovery directed:** policy allowed a next-step directive.

A delivered command is not automatically a successful equipment change.

## When PoolOS Disagrees With IntelliCenter

During ADVISE or SHADOW mode, disagreement is expected and useful. Review:

- whether both systems used the same current facts;
- whether IntelliCenter followed a native schedule or manual command;
- whether PoolOS identified a safety, cost, energy, or runtime concern;
- whether any observation was stale or unavailable;
- whether the recommendation remains explainable after the actual outcome.

Do not transfer authority merely because PoolOS produced a different answer.

## After a Restart or Outage

PoolOS should reconstruct state from current observations and persisted evidence.
It must not assume that a prior command or schedule remains valid. Confirm:

- operating mode;
- entity health and freshness;
- ownership state;
- armed capabilities;
- pending verification or recovery evidence.

If these cannot be confirmed, remain in or return to `OBSERVE`.

## Operator Responsibilities

The operator remains responsible for:

- approving authority changes;
- reviewing unresolved anomalies;
- maintaining valid entity mappings and credentials;
- testing rollback and manual control;
- keeping native safety functions operational unless formally replaced;
- deciding when conflicting schedules or automations may be retired.
