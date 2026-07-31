# ADR-031: Canonical Repository and IntelliCenter Integration Boundaries

- Status: Accepted
- Date: 2026-07-31

## Context

PoolOS evolved from an IntelliCenter-focused Home Assistant project into a vendor-independent
Python platform with stable observation, planning, decision, explanation, recovery, diagnostics,
and command-delivery boundaries.

The repository now contains both the installable `poolos` package and the source of a future
Pentair IntelliCenter Home Assistant custom integration. Accidental copies of Home Assistant
platform files were also present beneath `intellicenter/api/`, obscuring the intended boundary.

## Decision

Maintain two sibling source trees:

```text
poolos/             Installable vendor-independent Python package
intellicenter/      Separately deployed Home Assistant custom integration
```

Maintain `intellicenter/api/` as the integration's internal immutable read-model package.

The immutable API may contain normalization models and snapshot facades only. It must not contain
copied Home Assistant platform modules, integration metadata, translations, coordinators,
configuration flows, or project configuration files.

The root Python distribution continues to include only `poolos*`. The IntelliCenter integration
will later be deployed as the complete directory:

```text
/config/custom_components/intellicenter/
```

Public GitHub or HACS distribution is deferred until licensing and deployment requirements are
completed.

MyPy continues to check the `poolos` package. IntelliCenter remains covered by compilation, Ruff,
structural tests, and read-model unit tests until a Home Assistant-aware static-analysis boundary
is intentionally introduced.

No live automatic actuation is enabled by this decision.

## Consequences

### Positive

- Preserves the mature PoolOS architecture
- Keeps vendor integration and policy responsibilities explicit
- Avoids packaging Home Assistant runtime code in the PoolOS wheel
- Makes future manual or HACS deployment understandable
- Prevents accidental nested copies of integration files
- Allows IntelliCenter and PoolOS to evolve without creating duplicate control concepts

### Negative

- The repository has two distribution paths to document and validate
- IntelliCenter is not yet fully covered by MyPy
- Future HACS preparation will require metadata, release, installation, and upgrade work
- Cross-boundary integration tests will eventually require a Home Assistant-aware environment

## Alternatives Considered

### Move IntelliCenter beneath `poolos/vendors`

Rejected because the Home Assistant integration has its own lifecycle, metadata, platforms, and
runtime dependencies. It is not merely a PoolOS vendor adapter.

### Move the repository source immediately to `custom_components/intellicenter`

Deferred because it would create broad import, test, CI, and release-path churn during a hygiene
milestone without changing runtime behavior.

### Package IntelliCenter in the PoolOS wheel

Rejected because ordinary PoolOS consumers should not be forced to install Home Assistant and
controller-integration dependencies.
