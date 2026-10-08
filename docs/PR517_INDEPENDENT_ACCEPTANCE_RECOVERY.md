# PR 517 independent acceptance recovery — October 8, 2026

## Evidence and reproduced defect

The recovered independent matrix has 33 cases: 19 passed and 14 failed on
PR 517. The original scripts and logs remain outside the repository, unchanged.
Against merged main `f25dcf08625948f8efef0627735c339bd0bfbdbd` (PRs 518–519),
the same scripts produced 30 passes and three failures. All 14 original negative
failures passed, but these positive controls still rejected valid dispatch:

- `test_pending_body_dispatch_rechecks_material_authority[pool_on]`
- `test_pending_cleanup_revalidates_exact_current_body_entitlement[benign]`
- `test_filtration_native_callback_during_pump_delivery_must_not_invalidate_exact_context`

The denial was `automatic_filtration_context_stale`. Production runtime authority
composition compared every physical value and the entire circulation lease.
Consequently native motor convergence and normal confirmation bookkeeping were
treated as authority changes. The frozen signature also preceded the driver's
synchronous verification/reservation work. Separately, the live cleanup check
required the original observation epoch even when an equivalent authoritative
callback had legitimately advanced circulation arbitration.

## Correction and boundaries

The runtime freezes its material signature at exact command binding, after
synchronous driver preparation and before any transport await. It preserves
the immutable dispatch context; it does not rebind a queued command to a new
generation. The signature retains owner, lease/session/body-session identities,
generation, exact command/adoption provenance, BODY verification, domain
authority/permission, positive operator evidence, policy, configured pump intent,
native source identity, quality, confidence, freshness and topology facts.

Only non-authority feedback is excluded: confirmation timestamps/observation
bookkeeping and finite nonnegative actual motor RPM. Configured PMPCIRC intent
remains exact. Pool OFF-to-ON is compatible only while an independently admitted
BODY ON is pending; it creates no provenance. Acceptance and subsequent causal
verification remain required. Invalid motor feedback, missing evidence, Spa
activation, accessories, changed identities and authority changes still revoke
admission.

Cleanup checks the latest registry arbitration epoch while requiring the exact
existing verified BODY lease/session/circuit/receipt or adoption ID. The final
physical authority independently checks the original immutable command context
and its generation. Lease release/replacement, thermal handoff/reservation,
operator takeover, Reset, Maintenance, outage and unload still deny dispatch.
No freshness intervals, verification deadlines, command transport, ownership
creation, accounting, Solar/Spa policy or restart contracts change.

## Permanent acceptance coverage

`tests/test_filtration_gateway_adversarial_acceptance.py` migrates the original
27 adversarial cases and adds 15 real-gateway Pump cases. Only the physical
transport is a recorder: the HA runtime, delivery factory, manual command lock,
physical authority, cleanup currentness and canonical domain permission callback
are real. Callback races use deterministic lock barriers, not elapsed-time sleeps.
The Pump cases pair native settling/near-target/converged values with configured
intent, topology, missing evidence, invalid RPM, positive BODY/PUMP intent,
Maintenance, Reset and unload. A thermal reservation refused during acquisition
is explicitly distinguished from an actual authority transfer (covered by the
original cleanup handoff case).

`tests/test_filtration_original_acceptance.py` migrates the six original incident
and accounting controls, including actual debt accrual, wrong-session rejection
and protection of a truly manual Pool. Its lightweight delivery adapter is
supplemental to the real-gateway cases, not evidence of transport behavior.

On unmodified `f25dcf0`, the combined 48-case matrix has **7 failures / 41 passes**;
on the correction it has **48 passes**. The unchanged external original matrix
has **33 passes**. Existing full-suite tests remain mandatory for Solar, Spa,
Reset, restart, native arbitration, manual intent and shutdown quiescence.

## Deployment and physical acceptance

Software acceptance does not establish a commissioned operating cycle. Deploy
and verify the exact merged integration **and bundled core** before enabling any
control. Manifest version alone is insufficient proof of the loaded Git revision.
Do not clear legitimate manual suppression to force a Solar opportunity.

With authorized physical control and verified safe topology, observe legitimate
Pool BODY acquisition, probe 1500 RPM if required, ordinary circulation 2600 RPM,
Solar physically ACTIVE at 2900 RPM, and independently verified BODY/PUMP/THERMAL
authority. Then end thermal demand through the approved stimulus and verify
source OFF, Pool OFF, actual pump 0 and clean ownership termination.

Complete acceptance additionally requires evening TOU filtration, exact debt
satisfaction, BODY OFF acceptance and post-command Pool OFF/pump 0 verification,
then several authoritative idle epochs with no reacquisition or increasing
delivery count. Exercise a later independent opportunity from OFF.

STOP on missing/stale evidence, an unexpected command, Spa/accessory conflict,
incorrect ownership, fault, or failed shutdown. Preserve chronology before
authorized recovery. No physical commands, deployment, target changes, autonomy
changes or suppression clearing are performed by this repository recovery task.
