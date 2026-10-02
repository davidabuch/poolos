# PoolOS Current Development Handoff

## Current status — October 2, 2026

PoolOS is in **1.0 release-candidate readiness**.

The production Home Assistant installation is HACS-managed and physically commissioned with
scoped live control. The previous observation-only / global operating-mode commissioning model
is historical and must not be used as current runtime truth.

Current production integration line: `1.0.3`; release candidate: `1.0.4`.

PoolOS 1.0 is released. PR #389 introduced the coherent observation/accepted-command
chronology repair shipped in v1.0.3: truthful per-concept observation timestamps,
immutable authoritative input composition, and shared post-acceptance evidence
admission across orchestration, ownership, thermal execution, cleanup, and filtration.

Phase 4 commissioning of v1.0.3 exposed one fail-closed liveness gap: Waterfall,
Jets, and Slide could remain correctly OFF while their truthful startup observation
timestamps aged past strict freshness. Periodic reconciliation republished cached
native values without genuinely re-reading CIRCUIT STATUS, leaving Thermal blocked
with `thermal_orchestration_shared_hydraulic_inventory_incomplete` despite a
COMPLETE native inventory.

PR #391 fixes that commissioning defect without weakening chronology or freshness.
When shared-hydraulic safety evidence is stale, PoolOS performs one bounded read-only
native safety-topology reobservation for that evidence epoch through the existing
GetParamList path. It does not fabricate timestamps, restore ownership from state,
add a polling loop, or command equipment. v1.0.4 packages that hotfix for continued
physical re-commissioning.

See [ADR-111](adr/ADR-111-observation-and-command-consequence-chronology.md) for the
chronology model. PR #388 was closed as superseded by PR #389.


## Production control model

PoolOS is the default autonomous controller for its commissioned domains and yields only to
positive intentional operator control or higher-priority safety authority.

Authority is domain-scoped:

- BODY;
- PUMP;
- THERMAL.

Top-level runtime control profiles are descriptive:

- `SCOPED_LIVE`;
- `MANUAL_CONTROL`;
- `OBSERVE_ONLY`.

Production gates currently include:

- Automatic Filtration Execution;
- Automatic Thermal Execution;
- Thermal Live Execution;
- Grid Outage Physical Safety;
- Pool / Hot Tub sanitation;
- PoolOS Maintenance Mode (global physical-command deny).

## Verified 1.0-readiness state

Release `v0.11.104` removed the obsolete persisted `operating_mode=OBSERVE` setting and
replaced the hard-coded global command-delivery-disabled status with canonical runtime truth.

Physical production verification after the v0.11.104 restart showed:

- integration loaded successfully;
- observation health healthy;
- control profile `SCOPED_LIVE`;
- manual command delivery available;
- autonomous command delivery enabled;
- automatic filtration enabled;
- automatic thermal enabled;
- Thermal Live enabled;
- Grid Outage Physical Safety enabled;
- Maintenance Mode OFF.

The config-entry migration removed the legacy `operating_mode` field from live config data.

## Core behavioral contracts

Use these as normative sources rather than reconstructing behavior from historical handoff text:

- `docs/ownership/PoolOS_Ownership_Scenario_Contract.txt`
- `docs/ownership/OWNERSHIP_ARCHITECTURE_SPEC.md`
- `docs/PUMP_SPEED_SESSION_CONTROL_SPEC.md`
- sanitation ownership/scenario contract under `docs/ownership/`
- current ADRs for physical command authority, thermal execution, outage safety, and native transport.

Historical ADRs and release forensic records remain valuable evidence of why the current
architecture exists, but their milestone-era authority boundaries are not current product state.

## Current priorities

1. Complete 1.0 metadata/version alignment.
2. Finish universal pump capability abstraction so GPM controls are enabled only from positive
   adapter capability evidence and trustworthy native limits.
3. Continue minor edge-case hardening without weakening proven ownership, currentness,
   verification, shutdown, or restart behavior.
4. Physically commission any new or expanded authority before calling it complete.

## Engineering workflow

Continue autonomously through:

```text
inspect
-> diagnose
-> reproduce
-> implement
-> regression test
-> validate
-> push / PR
-> monitor CI and fix until green
-> merge
-> release
-> deploy
-> verify Home Assistant runtime
-> physically commission
-> document
```

Stop only at a genuine human/physical/Terminal/safety/design/permission boundary.

Repository truth is code/CI truth. Home Assistant is deployed-runtime truth. Physical equipment
behavior is final commissioning truth.

## Current 1.0 caveat

Do not equate "minor remaining edge cases" with permission to weaken fail-closed behavior.
Unknown capability, stale evidence, unexplained state, failed verification, or ambiguous
provenance must remain bounded according to the applicable domain contract.
