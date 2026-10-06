# Protected physical baseline — 2026-10-06

## Status

**PHYSICALLY COMMISSIONED — PASS**

Repository/runtime baseline: `af99164617cef7181b63284ad0069f9c64ffe1f0`.

This records a live Home Assistant + IntelliCenter commissioning result and is a regression-protection contract, not merely software-test evidence.

## Protected acceptance sequence

Starting from a clean Reset ownership epoch:

1. Pool target 90 F, Pool Solar active, pump 2900 RPM, automatic thermal CONVERGED.
2. Set Pool target to 80 F exactly once.
3. Pool Solar terminates cleanly; Pool BODY OFF; pump reaches 0; no automatic-thermal re-enable latch.
4. Opportunistic Spa qualifies only after Pool demand is satisfied.
5. PoolOS activates Spa BODY with PoolOS opportunistic provenance.
6. Spa temperature acquisition runs at 1500 RPM. The typed acquisition step has a bounded 120-second native-settling verification window; ordinary thermal commands retain the generic timeout.
7. After trusted Spa temperature is acquired, Spa selects Solar and reaches 2900 RPM.
8. Stable Spa state shows `session_kind=poolos_opportunistic`, BODY/Pump/Thermal PoolOS-owned, automatic thermal CONVERGED, and no re-enable latch.
9. Set Pool target to 90 F **exactly once**.
10. The first 90 F request must persist. A second request is not an acceptable workaround.
11. Pool demand preempts opportunistic Spa: Spa Solar terminates, Spa BODY turns OFF, stale Spa ownership is absent, and the Spa opportunity becomes ineligible while Pool demand exists.
12. Pool BODY activates and performs the 1500-RPM Pool temperature acquisition when required.
13. With trusted Pool temperature below the 90 F target and viable Solar, Pool selects Solar, reaches 2900 RPM, completes Solar-engagement confirmation, and returns to CONVERGED.

## Physically observed PASS

On 2026-10-06 the complete sequence above passed.

Final observed state:
- Pool target: 90 F
- trusted Pool temperature: 85 F
- Pool BODY: ON
- Spa BODY: OFF
- Solar: ON
- pump: 2900 RPM
- automatic thermal: CONVERGED
- observation health: HEALTHY
- BODY/Pump/Thermal ownership: PoolOS
- `automatic_thermal_reenable_required=false`
- no Gas selection
- no Pool target snapback
- no second 90 F command

## Regression rules

Changes touching thermal planning/execution, runtime ownership, currentness, target handling, IntelliCenter command delivery, Spa-session provenance, temperature acquisition, Reset/restart semantics, or Solar engagement must preserve this contract.

Required software protections include:
- Spa temperature-acquisition startup may exceed the generic 30-second command verification window but remains bounded at 120 seconds.
- Generic thermal command verification is not globally widened.
- PoolOS-created opportunistic Spa BODY activation retains PoolOS provenance during the uninterrupted live session.
- Returning Pool demand preempts PoolOS opportunistic Spa.
- The first Pool target increase from 80 F to 90 F persists.
- Handoff leaves no stale Spa BODY/Pump/Thermal ownership and does not set the re-enable latch.
- Pool Solar converges at 2900 RPM and must not select Gas in this acceptance scenario.

## Restart boundary

Live execution/ownership grants are intentionally not reconstructed merely because equipment remains physically active across a Home Assistant restart. An already-running Spa observed after restart must not be used as evidence for this uninterrupted-session acceptance test. Re-run from a clean Reset ownership epoch.

## Deployment rule

Do not deploy a mixed integration/core tree. For physical commissioning, install one exact repository revision using the repository's deterministic local HA package/HACS path so the Home Assistant integration and PoolOS core come from the same revision.

## Change-control rule

Do not import broad newer thermal/control architecture into this recovery baseline merely to resolve Git history or UI work. Make the smallest relevant change, protect it with regression tests, validate it, deploy the exact revision, and repeat the affected physical acceptance sequence when behavior is materially touched.
