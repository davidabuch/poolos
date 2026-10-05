# Filtration completion responsibility recovery

## Evidence and scope

This extends PR #456 on `fix/restore-observation-control-liveness`. Reference
main/v1.0.28 is `6329d0bfcbcf733d1bf01f336510de998aeb7480`; the original PR head is
`4bbb11b9b7d8da9b8933c3dcd5263f1e90aff530`. Both reproduce the same eight behavioral
failures below, plus the late-matching deadline regression. The earlier
idle-observation repair is retained unchanged.

The October 5 live report describes SATISFIED/zero debt, an ineligible filtration
opportunity, Pool ON/2600, PUMP acquisition, and no BODY origin. Repository replay
reproduces a reachable transition into that runtime signature. The supplied live
summary does not contain the individual native packets needed to establish that
this exact callback ordering caused all approximately 175 historical deliveries.
That attribution remains a physical-evidence question, not a software proof.

## Earliest lifecycle defect and reproduced chronology

1. A legitimate RUN_NOW starts from OFF. Accepted BODY_ON records an exact
   BODY receipt in `record_filtration_delivery`. Later native ON verifies BODY;
   an accepted and causally verified 2600 operation establishes verified filtration.
2. Debt becomes SATISFIED. The driver accepts provenance-bound BODY_OFF.
3. A temporarily missing BODY or pump observation suspends the verified lease.
4. A later usable Pool-OFF observation arrives while actual pump RPM is still 900.
   `_recover_suspended` previously released the entire lease and cleared the
   pending BODY_OFF attempt merely because Pool was OFF. No pump-zero verification
   had occurred. This consumed completion responsibility before completion.
5. A later publication carries the pre-OFF Pool-ON/2600 facts. With no lease,
   `_ordinary_pool_circulation_requires_baseline` recognizes ordinary circulation,
   and the driver accepts a new PUMP command despite satisfied debt. The new lease
   has no BODY origin. This matches the reported acquiring/no-BODY signature.

Even uninterrupted completed shutdown had no retained observation high-water mark:
older ON facts in a newer publication could create a fresh pump-only lease.
Additionally, the verified-lease transient-evidence return preceded the accepted
attempt timeout check, allowing an OFF attempt to remain pending beyond its fixed
45-second deadline. A matching OFF/zero frame after that deadline could also
verify late because the successful-match branch preceded timeout admission.
Neither issue is caused by the #456 idle-read fix.

## Historical scope of ordinary circulation

`139a2c1db385f4cda2c121be1e474ba5866bc391` introduced ordinary Pool RPM normalization
on September 29. `36ad8303576fe81b40bfd2dd3cf334a8f801df5d` added the satisfied-debt
manual-Pool regression. The intent was PUMP governance for plain operator Pool
circulation, without inventing BODY origin. Immediately afterward,
`61e68a2a8fcd72a2ef618e4d5fdebbfb0d8bdf23` restricted that path to leases without
BODY activation/adoption so owned filtration would still shut down.

That distinction is valid. The mistake was allowing completion recovery to discard
the very provenance used to distinguish an owned session from ordinary circulation.
Existing tests covered uninterrupted OFF/zero, unusable evidence before shutdown,
and genuinely manual satisfied-debt circulation separately. They did not cross
accepted OFF, evidence suspension, partial coastdown, and reordered ON publication.

## Repair and invariants

- Suspended accepted BODY_OFF uses the existing receipt-bound verifier, including
  strictly post-acceptance BODY-OFF **and actual pump zero**. It retains the exact
  lease, BODY receipt, operation, and absolute deadline until verification/failure.
- Transient evidence or a late match cannot bypass the original attempt deadline. Exhaustion retains
  verified BODY origin as an observable control fault; it creates no External owner
  and no new acquisition or indefinite command retries.
- Successful shutdown records the observed completion boundary. A later publication
  cannot acquire from Pool-ON facts at/before that boundary. This in-memory fence
  creates no ownership, timer, suppression, command, or restart restoration.
- An independently RUN_NOW, positive-debt, fresh, exclusively Pool-routed,
  source-free filtration purpose may use existing prospective BODY adoption.
  Equality, CREDITING alone, satisfied debt, a thermal successor, or an active
  session override cannot create this purpose.
- An existing verified PUMP-only session can enter that independent purpose through
  an exact predecessor-bound adoption. It creates a new generation/session and fresh
  adoption time; it copies no historical BODY receipt or old PUMP command authority.
  A fresh accepted PUMP operation must verify normally. Wrong predecessor, circuit,
  chronology, reused session, suspended owner, or yielded operator authority reject
  the upgrade.
- Without an independent purpose, manual Pool BODY remains unowned/external to
  PoolOS. Existing ordinary RPM governance is preserved; debt zero cannot grant
  BODY-OFF permission for that manual session.

Internal invariant: an owned/adopted session with satisfied debt and no successor
retains completion responsibility while terminating, verifying OFF/zero, or faulted;
it cannot turn its residual/pre-completion observations into a fresh pump-only lease.
An independently authorized later session can still acquire from fresh evidence.

No new timer, observer, loop, RPM, physical operation, freshness interval, attribution
heuristic, topology relaxation, or Reset workaround is introduced. Thermal/Spa,
outage Safety, native arbitration, and HA stop code are unchanged.

## Executable evidence

`tests/test_filtration_completion_lifecycle.py` adds 18 cases:

- two BODY/pump evidence-loss variants preserving receipt and OFF/zero verification;
- full partial-shutdown/reordered-ON reproduction ending with retained BODY_OFF,
  rather than acquiring PUMP with no BODY origin;
- 180 reordered publication epochs after completion, with no new command;
- actual TOU acquisition/accounting over six hours, exact zero, native startup
  3000/filtration 2600/coastdown 900/zero, verified shutdown, idle, later new-day need;
- prospective adoption at a new independent need and upgrade of already governed
  manual circulation, including an ordinary pump-session input;
- manual satisfied-debt plain/Solar circulation remains BODY-command-free;
- positive PUMP override cannot be erased by adoption;
- missing shutdown evidence respects the fixed deadline and retains faulted BODY;
- late matching OFF/zero cannot be accepted as timely verification;
- five invalid predecessor upgrade controls.

On each original revision, the behavioral subset gives **9 failed / 3 passed**;
six new API-specific negative controls are tested against the repaired interface.
The real-accounting normal path and true manual controls already passed: those
were not rewritten to make the defect disappear. Existing thermal handoff,
restart/adoption, operator-intent, hydraulic/Spa, outage ceiling, accounting/TOU,
arbitration/currentness, and shutdown-task suites remain required protections.

## Physical acceptance procedure — requires separate authorization

No HA/equipment access or commissioning was performed for this repair.

1. Verify Pool/Spa/source OFF, pump 0, healthy current evidence.
2. Create a legitimate filtration need using the approved accounting test method.
3. Confirm PoolOS BODY receipt or explicit prospective adoption, exact generation.
4. Verify physical Pool ON.
5. Verify configured/actual 2600 and stable owned filtration.
6. Advance genuine accounting toward zero using only the approved test method.
7. Observe exact SATISFIED/zero/ineligible transition and absence of any successor.
8. Confirm a single accepted provenance-bound BODY_OFF command.
9. Verify physical Pool OFF.
10. Verify actual pump zero and completion/lease closure.
11. Wait through several quiet and callback-driven reconciliation epochs.
12. Verify no new filtration acquisition or pump-only residual lease.
13. Verify accepted-delivery count remains stable.
14. Establish a genuinely new need and verify fresh acquisition from OFF.

This filtration test is the first physical release gate. Do not proceed to Solar
or Spa commissioning until it passes. On failure, preserve field timestamps,
receipts/deadlines, ledger, opportunity and generation evidence; add the faithful
regression and repeat this same test after separately reviewed release/deployment.
Real controller coastdown, callback ordering, installed transport responses, and
the original live packet attribution still require physical commissioning.
