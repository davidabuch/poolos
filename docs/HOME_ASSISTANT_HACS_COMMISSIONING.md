# PoolOS Home Assistant HACS Commissioning

## Purpose

This document defines the installation and commissioning boundary for the PoolOS Home Assistant
custom integration beginning with milestone 11.3A.

PoolOS is not yet approved for live equipment control. HACS packaging changes distribution only;
it does not increase PoolOS authority.

## Commissioning safety boundary

The Home Assistant integration is fixed to the following boundary through 11.4A:

```text
Operating mode: OBSERVE
Planning mode: SHADOW
Authority: NONE
Command delivery: DISABLED
Home Assistant service calls: NONE
Control entities: NONE
```

The integration may read configured Home Assistant entity state, evaluate the existing shadow
runtime, and publish diagnostic sensors. It may not register equipment-control services or create
switch, button, number, select, or climate control entities.

## HACS repository requirements

PoolOS uses the standard HACS integration repository layout:

```text
poolos/
  hacs.json
  brand/
    icon.png
  custom_components/
    poolos/
      manifest.json
      ...
```

The repository contains one HACS-managed integration under `custom_components/`. The custom
integration uses `translations/en.json` directly for runtime localization; it does not depend on
Home Assistant Core's build-time `strings.json` processing.

HACS requires the GitHub repository to be public. Making the repository public is an operator
release decision and is not performed by repository code. Do not attempt HACS installation while
the repository remains private.

## Runtime dependency strategy

The Home Assistant adapter depends on the vendor-independent PoolOS Python package that lives in
this same repository. HACS installs only `custom_components/poolos`, so the adapter cannot rely on
the repository checkout being present on the Home Assistant host.

For deterministic installation, `manifest.json` pins the core package to the same integration
release tag using a Home Assistant-supported Git requirement:

```text
poolos@git+https://github.com/davidabuch/poolos.git@v0.10.1
```

This means the Git tag matching the manifest version must exist before that integration version can be installed in Home Assistant.
Future Home Assistant integration releases must update both the manifest version and the pinned
PoolOS Git tag together.

## Release strategy

For each installable Home Assistant integration release:

1. Merge the milestone to `main` only after local and GitHub validation pass.
2. Create the matching Git tag referenced by `manifest.json`.
3. Publish a GitHub Release for that tag before using HACS for production installation.
4. Keep the repository public while HACS is expected to install or update it.
5. Never point the Home Assistant requirement at an unpinned branch such as `main`.

Milestone 11.3A uses integration version `0.6.0` and tag `v0.6.0`.
Milestone 11.3B uses integration version `0.7.0` and tag `v0.7.0`.
Milestone 11.3C uses integration version `0.8.0` and tag `v0.8.0`.
Milestone 11.3D uses integration version `0.9.0` and tag `v0.9.0`.
Milestone 11.4A advances the integration to `0.10.0`; after 11.4A is merged and green, create matching tag and release `v0.10.0` before any installation attempt.
Patch release `0.10.1` packages the post-11.4A commissioning fixes through PR #115 and pins the core dependency to matching tag `v0.10.1` for HACS delivery.


## 11.4A high-fidelity observation boundary

PoolOS observes mapped HA entities immediately on state/attribute changes and retains the 30-second
coordinator refresh only as periodic reconciliation. Event processing and reconciliation are serialized
through one read-only coordinator path. The persistent recorder continues to suppress insignificant
numeric noise while retaining meaningful transitions and five-minute checkpoints.

The pool/spa climate entities are interpreted according to their commissioning semantics: HA mode
`heat` means body/pump enabled, not heater firing. PoolOS derives body enabled from thermostat `Status`,
active heating demand from `hvac_action`, and observes gas-heater/solar outcomes separately. Current and
target temperatures plus raw `HEATER` and `HTMODE` attributes are recorded with attribute-level
provenance.

Pentair schedules and configured pool/solar/heat RPM presets are intentionally excluded from the
learning contract. Solar Preferred is optional explanatory context only. Freeze behavior remains under
Pentair protection and is deferred from locally learned control logic.

## Validation

The repository provides three complementary validation layers:

- existing PoolOS CI for Python tests, Ruff, MyPy, and source compilation;
- Hassfest validation for current Home Assistant custom-integration metadata and structure;
- HACS validation is triggered by pull requests, pushes to `main`, and manual dispatch, but the HACS
  validation job is intentionally skipped while the repository is private. Repository publication remains
  an explicit commissioning decision.

As of 11.4A the HACS workflow is ready to run automatically on pull requests and pushes to `main` in
addition to manual dispatch. Because HACS cannot validate this private repository with the workflow
token, the job is guarded by `github.event.repository.private == false`. A skipped HACS job while PoolOS
is private must not be interpreted as successful HACS validation. Once the repository is made public for
commissioning, the same workflow will execute `hacs/action` automatically.

## Installation sequence after 11.4A

Do not install PoolOS into the live Home Assistant instance after 11.3A alone. Complete and merge
11.3A through 11.4A first. Milestone 11.4A adds the high-fidelity event-driven observation boundary required before live learning, but live installation still requires explicit operator approval and the repository-publication decision.

When live observation commissioning is approved:

1. Confirm the repository is public and the current release/tag exists.
2. In HACS, open Custom repositories.
3. Add `https://github.com/davidabuch/poolos` as an Integration repository.
4. Download PoolOS.
5. Restart Home Assistant.
6. Open **Settings -> Devices & services -> Add integration**.
7. Select **PoolOS**.
8. Configure the required observation entity mappings.
9. Verify the PoolOS Control Center reports `OBSERVE`, authority `none`, and command delivery
   disabled before leaving commissioning mode.

## Rollback

If PoolOS fails to load or observation health is unacceptable:

1. Remove or disable the PoolOS config entry.
2. Do not change the existing IntelliCenter integration or its control schedules.
3. Remove the HACS PoolOS integration if needed and restart Home Assistant.
4. Existing IntelliCenter control remains authoritative throughout observation commissioning.

No PoolOS rollback step should issue a pool-equipment command.
