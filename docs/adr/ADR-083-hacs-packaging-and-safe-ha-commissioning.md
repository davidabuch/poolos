# ADR-083: HACS Packaging and Safe Home Assistant Commissioning Readiness

## Status

Accepted for milestone 11.3A.

## Context

The PoolOS Home Assistant integration already exists under `custom_components/poolos` and supports
UI configuration, read-only observation, shadow evaluation, and diagnostic publication. The
integration currently imports the vendor-independent `poolos` Python package from the repository
root.

That works in a development checkout but is not sufficient for HACS distribution because HACS
installs the integration directory under Home Assistant `custom_components`; it does not copy the
repository's top-level Python package into Home Assistant's Python import path.

PoolOS must become HACS-installable without weakening the commissioning boundary established by
ADR-073 through ADR-082.

## Decision

PoolOS will use the standard HACS integration repository layout and add root-level HACS metadata
and brand assets.

The Home Assistant integration version advances to `0.6.0`.

The vendor-independent PoolOS Python package will remain a separate package rather than being
copied or forked into `custom_components/poolos`. The integration manifest will install that core
package from the same public GitHub repository at a release-specific immutable Git tag:

```text
poolos@git+https://github.com/davidabuch/poolos.git@v0.6.0
```

The manifest version and pinned Git tag must move together for future installable releases.
Unpinned branch requirements are not permitted.

Hassfest will run on push and pull request. HACS validation will initially be a manual workflow so
that repository publication remains an explicit operator decision during private development.

The Home Assistant commissioning integration remains constrained to:

- `OBSERVE` operating mode;
- internal non-authoritative `SHADOW` evaluation;
- authority `NONE`;
- command delivery disabled;
- sensor-only entity publication;
- no Home Assistant equipment service calls;
- no control service registration.

## Consequences

### Positive

- HACS installation no longer depends on a development checkout existing on the Home Assistant
  host.
- Core PoolOS logic remains single-sourced instead of being duplicated inside the custom
  integration.
- Every installable integration release resolves a specific immutable core revision.
- HACS packaging does not create a new actuation path.
- Current Home Assistant and HACS validators become part of the repository's commissioning
  readiness process.

### Constraints

- HACS requires a public GitHub repository.
- The matching Git tag must exist before Home Assistant can install the pinned core requirement.
- Publishing the repository and creating a GitHub Release are release operations, not effects of
  merging this source code.
- PoolOS is not to be installed into the live Home Assistant instance until milestones 11.3A-D are
  complete and commissioning is explicitly approved.

## Rejected alternatives

### Duplicate the PoolOS core inside `custom_components/poolos`

Rejected because it creates two copies of the decision runtime and invites version drift across a
safety-critical boundary.

### Depend on the repository checkout existing on Home Assistant

Rejected because HACS does not install arbitrary repository-root Python packages into Home
Assistant's import path.

### Pin the dependency to `main`

Rejected because an unpinned branch makes installed behavior mutable and undermines deterministic
commissioning and rollback.

### Enable command delivery while packaging

Rejected because distribution readiness is independent from authority commissioning. Milestone
11.3A must not alter the control boundary.
