# PoolOS Local Home Assistant Development Package

## Purpose

This document describes the legacy/self-contained local deployment package used before
PoolOS became HACS-managed in the production Home Assistant installation.

It remains useful for development, isolated testing, or a repository state that cannot be
installed through HACS. It is **not** the current production deployment path and it is not
an OBSERVE-only product boundary.

## Current control model

A locally packaged PoolOS integration has the same code-level control architecture as the
matching repository revision. Physical control remains **scoped and independently gated**.
Packaging method does not grant or remove authority.

The runtime control profile is derived from actual transport and domain gates:

- `SCOPED_LIVE` — command transport is available and one or more autonomous domains are enabled;
- `MANUAL_CONTROL` — command transport is available but autonomous domains are disabled;
- `OBSERVE_ONLY` — no physical command-delivery transport is available.

Whether a local development install should be allowed to actuate real equipment is an operator
commissioning decision. Unknown or incomplete capability must fail closed.

## Packaging model

The normal production path uses the HACS release and the matching release-pinned PoolOS core
requirement. The local builder instead creates a self-contained deployment artifact:

```text
custom_components/
  poolos/
    ... Home Assistant integration files ...
    _vendor/
      poolos/
        ... exact PoolOS core package ...
```

For that generated artifact only, `manifest.json` contains an empty `requirements` list.
The integration bootstrap prefers `_vendor/poolos` when present, so Home Assistant does not
need GitHub access to obtain the core package.

Build the package from the repository root with:

```bash
python scripts/build_local_ha_package.py \
  --output /tmp/PoolOS_Local_HA_Development.zip
```

## Installation / validation

1. Use only a repository revision that has passed the full PoolOS CI suite.
2. Build a fresh local package; do not hand-edit vendored core files.
3. Replace the complete local `custom_components/poolos` directory.
4. Validate Home Assistant configuration.
5. Restart Home Assistant.
6. Verify the loaded integration version and observation health.
7. Verify the top-level control profile and every intended domain gate.
8. Treat any newly enabled physical authority as requiring physical commissioning.

For the production installation, use the HACS release workflow in
`HOME_ASSISTANT_HACS_COMMISSIONING.md` instead.

## Rollback

If a local development build fails to load or produces unacceptable runtime health:

1. Disable affected scoped-control gates when available.
2. Use PoolOS Maintenance Mode when a global PoolOS physical-command deny is required.
3. Replace the local package with the prior known-good package and restart Home Assistant.
4. Verify native IntelliCenter state after rollback.
5. Never restore stale equipment snapshots or manufacture prior PoolOS ownership.
