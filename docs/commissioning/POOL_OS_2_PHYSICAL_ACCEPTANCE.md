# PoolOS 2.0 Physical Acceptance Checklist

PoolOS 2.0 is not considered fully commissioned, and no post-2.0 release should be published, until the following physical behaviors are observed on the real IntelliCenter system.

## Release rule

- Automated CI, Hassfest, and HACS validation are necessary but not sufficient.
- A release candidate must remain on one commissioning branch/build until all required physical acceptance items pass.
- Do not mint successive public versions for individual commissioning defects.
- Any failed item stays on the same development line until repaired and physically re-tested.

## 1. Startup / liveness

- Home Assistant restart completes without Supervisor watchdog intervention.
- PoolOS native IntelliCenter transport becomes AVAILABLE.
- Observation health becomes HEALTHY with zero missing required concepts.
- No reconnect storm or repeated native reconciliation loop occurs.
- Recorder growth remains bounded; commissioning observers/evidence exporters remain disabled unless explicitly needed.

## 2. Automatic filtration acquisition

Starting from Pool OFF / pump 0 with legitimate filtration demand:

- Automatic Filtration gate is enabled/effective.
- PoolOS issues or adopts the Pool BODY session with explicit provenance.
- Pool becomes ON.
- A transient pump-session identity change must not permanently fault the PUMP domain.
- Any stale automatic-filtration pump context is discarded without physical dispatch and re-evaluated from a fresh authoritative epoch.
- Pump reaches the configured ordinary filtration target (currently 2600 RPM).
- BODY and PUMP provenance verify.
- Automatic filtration state reaches OWNED.
- Filtration credit accumulates only from valid circulation.

## 3. Automatic filtration terminal cleanup

When filtration debt reaches zero:

- PoolOS recognizes no further immediate circulation requirement.
- Verified BODY provenance remains sufficient to authorize owned BODY_OFF cleanup even if an earlier PUMP-domain attempt faulted.
- PoolOS commands Pool OFF exactly once through the authorized cleanup path.
- Native Pool state verifies OFF.
- Native pump RPM verifies 0.
- Filtration ownership is released.
- No terminal cleanup binding error remains latched.
- A later legitimate filtration opportunity can reacquire from a clean unowned state.

## 4. Pool thermal / Solar

- Pool thermal opportunity is recognized from fresh native evidence.
- Temperature-probe behavior follows commissioned policy.
- Solar source engages only when eligible.
- Pump target follows active delivery (currently Solar 2900 RPM).
- Source and pump ownership verify before the session is considered owned.
- Solar loss / reacquisition behaves correctly without unnecessary pump cycling.
- Target-down -> shutdown -> target-up reacquisition passes.

## 5. Pool Gas

- Gas is selected only when policy authorizes it.
- Pump target follows active Gas delivery (currently 3000 RPM).
- Gas termination cleans up source/body/pump ownership correctly.

## 6. Hot Tub / Spa

- User Hot Tub ON is recognized as a Spa session, not misclassified as Pool manual suppression.
- Opportunistic Spa heating follows commissioned Solar/Gas source policy.
- Pump target follows active Spa delivery.
- Mid-session source switching is safe.
- User Spa OFF terminates the session cleanly.
- Pool autonomy resumes only from fresh eligible evidence.

## 7. Grid outage safety

- Grid Outage Physical Safety remains persistently armed.
- Confirmed outage applies the commissioned RPM ceiling and disables incompatible loads/features.
- Safety ownership supersedes normal autonomy while active.
- Grid return clears Safety authority from fresh authoritative evidence.
- Normal ownership is not fabricated during restoration.

## 8. Sanitation

- Pool sanitation session starts, runs at commissioned target, and terminates cleanly.
- Hot Tub sanitation session starts, runs, and terminates cleanly.
- Outage interruption pauses sanitation and preserves remaining duration.
- Resume after grid return does not double-count elapsed time.

## 9. Manual controls / suppression

- Manual Pool OFF immediately wins over automation.
- Transient manual Pool OFF suppression is bounded to the current operational day/opportunity and clears without requiring a hidden manual reset.
- Manual Pool ON/OFF and Spa ON/OFF remain usable.
- Manual pump/source changes do not get overwritten without a fresh authorized opportunity.

## 10. Restart / recovery

- Clean restart with equipment OFF returns to unowned healthy state.
- Restart during legitimate active circulation fails safe and follows the commissioned recovery contract.
- No stale pre-restart command context is reused.
- No restart creates fabricated physical ownership.

## 11. Final release gate

Before publishing any new PoolOS version after v2.0.0:

- Every required physical item above is PASS, or explicitly documented as not applicable.
- No unresolved PoolOS health incident exists.
- No Supervisor watchdog loop has occurred during commissioning.
- CI, Hassfest, and HACS validation are green on the exact release tree.
- The release tree is the exact tree physically commissioned.
