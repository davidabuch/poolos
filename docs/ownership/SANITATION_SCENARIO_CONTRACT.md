# PoolOS Sanitation Scenario Contract

Status: Accepted design contract from owner review, September 27, 2026.

## Purpose

Sanitation is a first-class, bounded PoolOS maintenance purpose. It is not a
manual override, a normal Thermal session, or a loose Home Assistant automation.
It has explicit BODY, PUMP, and THERMAL semantics and must remain subordinate to
higher safety authority such as a confirmed grid outage.

This contract governs both **Pool Sanitation** and **Hot Tub Sanitation**.

## Configuration

PoolOS exposes configurable:

- sanitation pump RPM;
- Pool sanitation duration;
- Hot Tub sanitation duration.

The initial defaults are 3200 RPM and 240 minutes for each body. These values
are configuration, not hard-coded policy assumptions.

## Common session rules

1. Pool and Hot Tub sanitation are mutually exclusive. A second sanitation
   request is rejected while the other body has an active sanitation session.
2. Starting sanitation creates a new, explicit PoolOS sanitation authority
   generation.
3. Sanitation outranks ordinary Pool thermal opportunities, Hot Tub thermal
   policy, and normal filtration execution.
4. Confirmed grid-outage safety outranks sanitation.
5. Sanitation forces the active sanitation body's physical heat source OFF.
   Gas and Solar selection are not permitted while sanitation is active.
6. BODY and PUMP are then established for the configured sanitation body and
   configured sanitation RPM.
7. The sanitation countdown advances only while fresh authoritative evidence
   verifies all of:
   - grid is available;
   - sanitation body is active;
   - the other body is inactive;
   - heat source is OFF;
   - observed pump RPM is within the commissioned tolerance of the sanitation
     target;
   - required BODY/PUMP/THERMAL evidence is usable.
8. Time spent starting, verifying, unavailable, paused, or outside the required
   physical state does not count toward sanitation duration.
9. Session remaining time is durable across Home Assistant restart. Restart
   restores durable sanitation intent and remaining work, not old physical
   ownership or old verification continuity. Fresh evidence is required before
   countdown resumes.
10. On confirmed grid outage, sanitation pauses. Grid-outage safety owns its
    reduction envelope. When grid service returns, the same sanitation session
    resumes from its remaining duration after fresh verification.
11. A positive manual PUMP change follows the ordinary concept-specific
    ownership contract. PUMP yields to the operator and sanitation time pauses.
    A deliberate return to PoolOS's exact current sanitation RPM is implicit
    PUMP hand-back after verification.
12. A manual BODY OFF for the sanitation body means **Cancel Sanitation**.
    PoolOS turns/keeps that body OFF, ends the sanitation session, and the HA
    sanitation toggle becomes OFF. It does not create a persistent automatic
    suppression.
13. On normal duration completion, PoolOS turns the sanitation body OFF and ends
    the sanitation generation only after authoritative OFF verification.
14. Completion or cancellation is a legitimate fresh policy boundary. PoolOS
    retires sanitation provenance, obtains fresh evidence, and reevaluates
    normal policy. It does not require the broad Reset PoolOS Control workflow.
15. Sanitation relinquishment does not manufacture External ownership and does
    not persistently alter Eco Heat, target temperatures, filtration policy, or
    other durable user policy.
16. Unknown, stale, contradictory, or unusable evidence fails closed and pauses
    progress rather than counting time or assuming success.

## Hot Tub Sanitation

- BODY = PoolOS sanitation authority for Hot Tub.
- PUMP = PoolOS sanitation authority at configured sanitation RPM unless a
  positive manual PUMP override is active.
- THERMAL = PoolOS sanitation authority with heat forced OFF.
- Hot Tub sanitation time does **not** count as Pool filtration credit.

## Pool Sanitation

- BODY = PoolOS sanitation authority for Pool.
- PUMP = PoolOS sanitation authority at configured sanitation RPM unless a
  positive manual PUMP override is active.
- THERMAL = PoolOS sanitation authority with heat forced OFF.
- Verified Pool sanitation circulation **does count toward the existing
  filtration obligation** under the normal authoritative filtration ledger.
  PoolOS must not create a second sanitation-specific filtration ledger.

## Required Home Assistant observability

At minimum expose:

- Pool Sanitation toggle;
- Hot Tub Sanitation toggle;
- active/inactive/paused/starting/completing state;
- sanitation body;
- remaining seconds;
- configured duration;
- configured sanitation RPM;
- BODY/PUMP/THERMAL sanitation owner;
- pump manual-override state;
- grid-outage pause state/reason;
- latest sanitation reason/failure;
- restart-durable status;
- whether Pool sanitation contributes filtration credit.

## Commissioning requirements

Before calling the feature commissioned, physically verify at minimum:

1. Hot Tub already heating -> Hot Tub Sanitation starts -> heat OFF -> sanitation
   RPM -> timer advances.
2. Gas/Solar request during Hot Tub Sanitation is rejected or immediately
   prevented from becoming active.
3. Manual Hot Tub OFF cancels sanitation and leaves Hot Tub OFF.
4. Home Assistant restart during active sanitation preserves remaining duration,
   then resumes only after fresh evidence.
5. Confirmed grid outage pauses sanitation; grid return resumes remaining work.
6. A new Pool Solar opportunity cannot preempt active Hot Tub Sanitation.
7. Normal completion turns body OFF and normal PoolOS autonomy later reacquires
   from fresh policy/evidence.
8. Manual pump change yields PUMP only; return to sanitation RPM hands PUMP back.
9. Pool Sanitation follows the same rules and its verified circulation advances
   the existing filtration ledger.
10. Pool and Hot Tub sanitation cannot run simultaneously.
