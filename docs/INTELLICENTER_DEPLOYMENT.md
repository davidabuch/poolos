# IntelliCenter Home Assistant Deployment Boundary

## Current Status

The IntelliCenter integration is not installed in Home Assistant yet. The private Git repository
is the current development source of truth.

Do not copy partial files into Home Assistant during PoolOS repository-cleanup work.

## Future Manual Installation Layout

When the integration is ready for runtime testing, the complete repository directory:

```text
intellicenter/
```

will be installed as:

```text
/config/custom_components/intellicenter/
```

The deployed directory must include:

```text
__init__.py
config_flow.py
const.py
coordinator.py
binary_sensor.py
climate.py
cover.py
diagnostics.py
light.py
number.py
select.py
sensor.py
switch.py
manifest.json
strings.json
translations/
api/
```

The `api/` directory must contain only the immutable read-model package.

## PoolOS Packaging Is Separate

The root PoolOS wheel intentionally excludes `intellicenter/`.

```bash
python -m pip install -e ".[dev]"
```

installs the `poolos` package for development. It does not deploy a Home Assistant custom
component.

## Future HACS Preparation

Before HACS distribution, complete at least the following:

1. Select and add a public-use license.
2. Confirm repository and integration naming.
3. Validate `manifest.json` against the target Home Assistant release.
4. Define supported Home Assistant and Python versions.
5. Add installation, upgrade, rollback, and removal instructions.
6. Add Home Assistant-aware import and config-flow tests.
7. Validate a clean manual installation under `custom_components/intellicenter`.
8. Decide whether the repository is a default HACS integration or a custom repository.
9. Add release tags and a repeatable release process.
10. Confirm diagnostics contain no credentials or private controller information.

HACS packaging must not be treated as complete merely because the repository is public.
