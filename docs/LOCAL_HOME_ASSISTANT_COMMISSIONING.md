# PoolOS Local Home Assistant Commissioning

## Purpose

PoolOS may be commissioned locally while the GitHub repository remains private and before public/HACS distribution is appropriate.

The local package is still observation-only:

```text
Operating mode: OBSERVE
Planning mode: SHADOW
Authority: NONE
Command delivery: DISABLED
Home Assistant service calls from the commissioning integration: NONE
Control entities: NONE
```

The existing IntelliCenter integration remains authoritative.

## Packaging model

The source repository keeps the normal release-pinned PoolOS core requirement used by the future HACS distribution path. The local commissioning builder instead creates a self-contained deployment artifact:

```text
custom_components/
  poolos/
    ... Home Assistant integration files ...
    _vendor/
      poolos/
        ... exact PoolOS core package ...
```

For that generated artifact only, `manifest.json` contains an empty `requirements` list. The integration bootstrap prefers `_vendor/poolos` when present, so Home Assistant does not need GitHub credentials and does not download the private repository.

Build the deployment package from the repository root with:

```bash
python scripts/build_local_ha_package.py \
  --output /tmp/PoolOS_Local_HA_Commissioning.zip
```

## Installation

1. Back up the Home Assistant configuration before installing a new custom integration.
2. Extract the generated ZIP.
3. Copy `custom_components/poolos` into `/config/custom_components/poolos` on the Home Assistant host.
4. Restart Home Assistant.
5. Open **Settings -> Devices & services -> Add integration** and select **PoolOS**.
6. Configure the observation mappings.
7. Verify PoolOS reports `OBSERVE`, authority `none`, and command delivery disabled.
8. Confirm the existing IntelliCenter integration and schedules/controls remain unchanged.

## Update process

For each local PoolOS update, build a fresh local commissioning ZIP from the validated repository state, replace the entire `/config/custom_components/poolos` directory, and restart Home Assistant. Do not hand-edit the vendored PoolOS core on the Home Assistant host.

## Rollback

If PoolOS fails to load or observation health is unacceptable, remove/disable the PoolOS config entry and remove `/config/custom_components/poolos`, then restart Home Assistant. No rollback step should issue an equipment command.
