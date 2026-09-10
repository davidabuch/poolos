# PoolOS Pump Speed and Session Control Specification

## Status

Approved behavioral design as of September 9, 2026.

This document records the accepted pump-speed/session contract developed before implementation.

Implementation is intentionally divided into slices. Not every behavior described here exists in current production code.

`AGENTS.md` remains the higher-precedence repository safety constitution.

---

## 1. Fundamental Separation

Pump RPM governance and body-activation ownership are separate concepts.

Body ownership determines whether PoolOS may:

- activate a body;
- deactivate a body;
- perform body cleanup/termination.

Pump governance determines the appropriate RPM of an already-active hydraulic body.

PoolOS may govern RPM without thereby obtaining body shutdown authority.

Changing an external body's PMPCIRC does not manufacture BODY_ACTIVATION provenance.

---

## 2. Configurable Baselines

The following values must become user-configurable PoolOS policy:

- ordinary / no-heat / filtration RPM: default 2600;
- Solar heating RPM: default 2900;
- Gas heating RPM: default 3000;
- temperature probe RPM: default 1500;
- priming RPM: default 3000;
- grid outage RPM: default 1500.

Preserve existing spillway RPM semantics, currently default 2900.

High Speed is separate and belongs to a later implementation slice.

One loaded PoolOS config entry must ultimately have one canonical effective baseline policy used consistently across planning, authorization, execution, and delivery.

---

## 3. Operating Sessions

Pump RPM behavior is session-based.

Important session/purpose categories include:

- ordinary circulation;
- Solar heating;
- Gas heating;
- temperature acquisition/probe;
- priming;
- grid outage.

Session identity includes the active body.

True session boundaries include:

- body OFF;
- Pool -> Hot Tub;
- Hot Tub -> Pool;
- Ordinary -> Solar;
- Solar -> Ordinary;
- Ordinary -> Gas;
- Gas -> Ordinary;
- Solar -> Gas;
- Gas -> Solar;
- probe start/end;
- priming start/end;
- outage start/end;
- another genuine hydraulic/safety purpose transition.

Routine refreshes and accounting updates are not session boundaries.

---

## 4. Configured RPM Is the Session Default

The configured RPM for a session is its default, not a setpoint PoolOS must continuously fight to preserve after deliberate user intervention.

Examples with defaults:

- ordinary: 2600;
- Solar: 2900;
- Gas: 3000;
- probe: 1500;
- priming: 3000.

Pool and Hot Tub use exact body-bound PMPCIRC assignments.

---

## 5. Actual Heating State Determines Heat Purpose

RPM purpose follows actual operating state.

Merely selecting/configuring a heat source does not create a heating session.

Examples:

- Solar selected but not active -> ordinary/no-heat;
- Gas selected but burner not active -> ordinary/no-heat;
- Solar actually active -> Solar session;
- Gas actually active -> Gas session.

Heat-source activation or termination is a session transition.

---

## 6. Direct Manual RPM Override

An explicit user change through the Pool RPM or Hot Tub RPM control creates a manual RPM override for the current session.

Example:

ordinary baseline 2600
user sets 3200
result: remain 3200 for the rest of that ordinary session.

PoolOS must not immediately restore 2600.

The override is cleared by a true session transition.

Routine coordinator refresh, temperature updates, filtration accounting, or planner reevaluation do not clear it.

---

## 7. Session Transition Clears Prior Manual Override

Examples:

ordinary manual 3100 -> Solar begins -> configured Solar RPM.

Solar manual 3200 -> Solar ends -> configured ordinary RPM, if ordinary circulation should actually continue.

Gas manual 3300 -> Gas ends -> configured ordinary RPM, if ordinary circulation should continue.

Pool manual override -> Hot Tub -> Hot Tub starts from its appropriate configured policy.

---

## 8. IntelliCenter Startup RPM Is Not a Manual Override

Turning on Pool or Hot Tub may cause IntelliCenter to use a preconfigured PMPCIRC value such as 2900.

That startup value is not automatically evidence that the user explicitly selected 2900.

Example:

user turns Pool ON
no heat active
IntelliCenter PMPCIRC = 2900
ordinary baseline = 2600

PoolOS may establish ordinary 2600 RPM governance without gaining body shutdown ownership.

---

## 9. Body-Specific RPM Controls

Pool and Hot Tub require separate controls.

Pool RPM:

- operates only Pool PMPCIRC;
- available only while Pool is active.

Hot Tub RPM:

- operates only Spa/Hot Tub PMPCIRC;
- available only while Hot Tub is active.

Never assume hard-coded PMPCIRC object IDs.

Use native dynamic body resolution and native pump limits.

Configured PMPCIRC speed and actual pump RPM remain separate evidence.

---

## 10. High Speed

High Speed is a user-controlled system-level minimum RPM floor.

Effective RPM while High Speed is ON is conceptually:

`max(session requirement, High Speed floor, active legitimate feature minimums)`

Examples:

ordinary 2600 + High Speed 3200 -> 3200

Solar 2900 + High Speed 3200 -> 3200

Gas 3300 + High Speed 3200 -> 3300

High Speed is not the same concept as direct manual RPM override.

---

## 11. Direct RPM Change Cancels High Speed

If High Speed is ON and the user directly changes RPM:

- High Speed turns OFF;
- the chosen RPM becomes the manual override for the current session.

Example:

High Speed 3200
user sets 3000
High Speed OFF
current-session override = 3000.

---

## 12. Enabling High Speed Cancels Direct Manual Override

If a manual RPM override exists and High Speed is enabled:

- manual override ends;
- High Speed becomes the applicable floor.

The old direct RPM override does not remain hidden underneath High Speed.

---

## 13. High Speed Lifetime

High Speed may survive heat-source changes within the same body.

High Speed must turn OFF when:

- Pool turns OFF;
- Hot Tub turns OFF;
- Pool changes to Hot Tub;
- Hot Tub changes to Pool;
- grid outage entry occurs;
- user directly changes RPM.

High Speed therefore does not survive body OFF/ON cycles or body transitions.

---

## 14. Configuration Changes During Active Session

If an active session has no manual override and its configured baseline changes, the new configured baseline may apply to that current session after normal runtime reconciliation.

If a manual override exists, preserve the manual override until that session ends.

Changing High Speed configured value while High Speed is active updates the floor.

Saving configuration itself must not directly issue equipment commands.

---

## 15. Grid Outage Intended Future Behavior

Grid outage ultimately becomes a one-time protective intervention for each confirmed outage entry.

On outage entry PoolOS should perform the configured safety actions such as:

- Spa OFF if active;
- disable relevant features;
- disable Gas/Solar heat;
- turn High Speed OFF;
- reduce Pool circulation to configured outage RPM if circulation is required.

After that initial protective action completes, deliberate user control is respected.

A user may later increase RPM or manually use the Hot Tub during the same outage.

PoolOS must not continuously fight that deliberate post-kill user choice merely because outage remains active.

Grid restoration begins a new normal session.

This redesign is deferred to the dedicated Grid Outage slice.

---

## 16. Externally Activated Body RPM Governance

PoolOS may govern the RPM of an already-active external Pool or Hot Tub.

Example:

user turns Pool ON
no heat
IntelliCenter starts at 2900
ordinary baseline 2600

PoolOS may set exact Pool PMPCIRC to 2600.

This does NOT authorize PoolOS to turn Pool OFF.

---

## 17. Later Adoption of an Externally Started Body

An external activation may later become PoolOS-owned only when PoolOS independently develops a policy reason that would itself have caused activation at that moment.

Example:

08:00 user turns Pool ON early.

At 08:00 PoolOS has no activation purpose and body remains external.

09:00 Solar becomes valid and PoolOS independently would activate Pool for Solar.

PoolOS may then explicitly adopt the active Pool session under a separately implemented evidence-backed adoption contract.

Matching active state by itself is not adoption.

---

## 18. Manual Body OFF

User body OFF preempts PoolOS.

Effects include:

- end current pump session;
- clear session-scoped direct RPM override;
- High Speed OFF;
- relinquish relevant control;
- arm body-specific automatic suppression where currently required;
- do not immediately reactivate the body.

---

## 19. Manual Body ON After Suppression

If the user later explicitly turns that same body ON:

- clear that body's Resume-required suppression;
- permit normal PoolOS autonomy again.

But this new activation was caused by the user.

Do not manufacture PoolOS BODY_ACTIVATION provenance from suppression clearing.

The body may later be adopted if PoolOS independently develops a valid activation purpose.

---

## 20. TOU-Aware Solar Completion

When Pool Solar reaches target, do not automatically continue ordinary circulation merely because filtration debt remains.

Decision order:

1. Is opportunistic Hot Tub Solar currently valid?
2. Is Pool filtration independently required to run now?
3. Can remaining filtration debt be deferred under TOU policy?

If Hot Tub Solar opportunity exists:

- transition Pool -> Hot Tub;
- begin Hot Tub Solar session;
- use Solar RPM;
- preserve Pool filtration debt independently.

If no Hot Tub opportunity exists and filtration can be deferred:

- Pool may shut OFF when PoolOS has valid body cleanup authority;
- debt remains for preferred catch-up period.

Only continue ordinary Pool circulation immediately if filtration policy independently requires it now.

---

## 21. Filtration Accounting Is Not a Pump Session

`CREDITING`, `SATISFIED`, and other filtration accounting dispositions do not inherently create pump-session transitions.

Solar may continue after filtration becomes satisfied if useful Solar heating remains required.

Externally active circulation may earn filtration credit without granting PoolOS body shutdown ownership.

---

## 22. RUN_NOW

If Pool is externally active, RUN_NOW may use existing circulation and earn credit without manufacturing body activation ownership.

If Pool is OFF and autonomous Pool activation is permitted, RUN_NOW may legitimately activate and later clean up the Pool under proper ownership/provenance.

---

## 23. Probe

Probe RPM is configurable.

Probe entry and exit are session transitions.

A direct manual RPM change during probe may be allowed only if it remains compatible with actual minimum acquisition/hydraulic requirements.

A true safety minimum outranks operator preference.

---

## 24. Priming

Priming RPM is configurable.

Priming entry and exit are session transitions.

If priming speed represents a true pump-protection requirement, operator RPM changes may not violate that required minimum.

Do not weaken pump protection to implement session overrides.

---

## 25. Feature RPM Floors

Some hydraulic features may impose true minimum RPMs.

These are separate from:

- session baseline;
- direct manual override;
- High Speed.

Effective RPM must honor the highest currently legitimate minimum.

A user may choose a higher speed.

A user may not force a speed below a genuine active hydraulic/safety minimum.

Removing the feature floor does not itself erase a valid manual override unless the underlying session changes.

---

## 26. No Active Body / Contradictory Topology

If Pool and Hot Tub are both OFF but pump RPM is nonzero, do not guess a body and issue normal automatic RPM commands.

If both bodies appear active or topology is contradictory, fail closed for new automatic RPM reconciliation.

Wait for authoritative resolution.

---

## 27. Command Currentness and Races

Immediately before physical RPM mutation, confirm the operation still belongs to the current purpose/session.

Example:

ordinary 2600 planned
Solar activates before delivery

Do not send stale ordinary 2600.

Re-evaluate for Solar.

If a user explicitly changes RPM while a PoolOS RPM command is pending verification:

- user wins;
- stale PoolOS verification/continuation is abandoned;
- user value becomes the current-session override where allowed.

---

## 28. Accepted Is Not Verified

Pump command lifecycle remains:

request
-> authorization
-> delivery
-> accepted receipt
-> later authoritative configured-speed observation
-> actual RPM convergence where required
-> verification.

Accepted delivery alone does not prove the physical result.

Timeout must not create ownership or blind repeated hammering.

---

## 29. Restart / Reload

Restart does not reconstruct manual override intent from RPM equality or mismatch.

Example:

restart sees ordinary Pool active at 3100
configured baseline = 2600

PoolOS cannot infer that 3100 definitely represents a deliberate manual override.

A bounded reconciliation approach is required before future automatic normalization.

Likewise, matching 2600 after restart does not manufacture PoolOS body or pump ownership.

---

## 30. Core Precedence Summary

For normal operation:

1. true safety/hydraulic minimums;
2. current body and actual operating purpose;
3. legitimate active feature minimum floors;
4. High Speed floor if active;
5. direct user RPM override where allowed;
6. configured session baseline.

The implementation may structure this differently internally, but behavior must preserve the approved semantics.

Ownership remains a separate axis determining body activation/cleanup authority.

---

## 31. Implementation Sequence

Implement incrementally:

1. canonical configurable pump baselines;
2. explicit pump sessions and direct manual RPM overrides;
3. ownership-independent active-body RPM governance;
4. High Speed;
5. explicit body adoption;
6. TOU/Solar completion/opportunistic Hot Tub handoff;
7. grid-outage behavioral redesign.

Do not combine all seven slices into one implementation.
