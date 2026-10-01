# PoolOS Home Assistant Installation, Safety, and Release Boundary

## Purpose

This document describes the current Home Assistant deployment boundary for PoolOS.
It supersedes the original observation-only HACS commissioning instructions.

PoolOS began as an OBSERVE/SHADOW integration and was commissioned incrementally into
physical control. The production architecture intentionally preserves the safety gates
created during that process, but the integration is no longer observation-only.

## Current runtime model

PoolOS uses **scoped live control**. There is no single global switch that grants every
subsystem unrestricted equipment authority.

The top-level runtime control profile is derived from the actual live gates:

- `SCOPED_LIVE` — one or more autonomous physical-control domains are enabled and the
  independent command transport is available;
- `MANUAL_CONTROL` — the command transport is available but no autonomous domain is enabled;
- `OBSERVE_ONLY` — no physical command-delivery transport is currently available.

Read-only evidence and advisory objects may continue to expose
`command_delivery_enabled: false`. That is intentional: recommendations, observation-source
selection, recorder evidence, and other diagnostic artifacts do not themselves receive
physical authority.

## Physical-control domains

PoolOS keeps independent authority and verification boundaries for:

- manual Pool/Spa climate and supported equipment controls;
- automatic filtration execution;
- automatic thermal execution;
- Thermal Live Execution;
- grid-outage physical safety;
- Pool and Hot Tub sanitation;
- bounded pump target/session control.

A domain being enabled does not imply that it will issue a command. Current evidence,
ownership, policy, maintenance state, controller mode, transport readiness, exact target
identity, and final verification remain mandatory.

## Safety model

Important production properties include:

- unknown, stale, contradictory, or incomplete evidence fails closed;
- operator actions can preempt only the domains they actually affect;
- physical equality does not manufacture ownership;
- restart does not reconstruct stale command authority;
- accepted delivery is not completion until later authoritative evidence verifies the result;
- grid-outage safety is reduction-only and never restores stale pre-outage state;
- maintenance mode remains a global physical-command deny;
- RPM/GPM command capability requires positive pump capability evidence;
- read-only advisory and retrospective subsystems remain non-authoritative.

## HACS packaging

PoolOS uses the standard HACS integration layout:

    poolos/
      hacs.json
      brand/
      custom_components/
        poolos/

Each installable release pins the PoolOS Python package to the matching Git tag in
`custom_components/poolos/manifest.json`. The Git tag and GitHub Release must therefore
exist before HACS installation or upgrade.

## Release sequence

For each release:

1. Merge only after PoolOS CI, Hassfest, and HACS validation pass.
2. Ensure the integration version and pinned PoolOS core tag match.
3. Create the matching annotated Git tag.
4. Publish the matching GitHub Release.
5. Refresh HACS repository information.
6. Install the new release.
7. Validate the Home Assistant configuration.
8. Restart Home Assistant.
9. Verify the loaded PoolOS version, observation health, command transport, scoped control
   status, and error log.
10. Physically commission any new authority or equipment behavior before calling that behavior
    complete.

## 1.0 readiness

The 1.0 release line represents the transition from commissioning-era terminology to the
current production architecture. Before tagging 1.0, repository documentation, diagnostics,
System Health, dashboard terminology, configuration migrations, and release metadata must all
describe the same scoped-live model.

Historical ADRs remain historical evidence and are not rewritten merely because later work
superseded their commissioning assumptions. Current top-level documentation and runtime
diagnostics are authoritative for the present product state.

## Rollback

If a PoolOS release fails to load or produces unacceptable runtime health:

1. Return any affected scoped control gate to OFF where possible.
2. Use Maintenance Mode when a global PoolOS physical-command deny is required.
3. Reinstall the prior known-good HACS PoolOS release and restart Home Assistant.
4. Verify native IntelliCenter state directly after rollback.
5. Do not restore stale equipment snapshots or fabricate prior PoolOS ownership.

Rollback is a software/runtime recovery action; it must not manufacture equipment commands.
