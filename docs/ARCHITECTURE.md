# PoolOS Repository Architecture

## 1. Purpose

PoolOS is a vendor-independent platform for observing, evaluating, deciding, explaining,
recording, and publishing intelligent pool and spa operations.

The repository also contains the source of a future Home Assistant custom integration for
Pentair IntelliCenter equipment. These are related components with separate responsibilities and
distribution boundaries.

## 2. Canonical Repository Boundaries

```text
poolos repository root
├── poolos/              Installable vendor-independent Python package
├── intellicenter/       Home Assistant custom integration source
│   └── api/             Immutable internal IntelliCenter read models
├── tests/               Shared automated validation
├── docs/                Architecture and engineering records
└── config/              Example installation configuration
```

The repository root and the nested `poolos/` package intentionally use the same name.

### 2.1 PoolOS package

The `poolos/` package owns:

- Canonical operations and domain models
- Typed observations
- Evaluation contexts and triggers
- Policies, goals, planning, and alternative ranking
- Decision intelligence and stability
- Human and technical explanations
- Flight-recorder decisions
- Restart recovery and deterministic replay
- Runtime diagnostics and golden scenarios
- Vendor-independent Home Assistant observation and publication boundaries
- Hardware and vendor command-delivery abstractions

PoolOS does not currently perform live automatic actuation.

### 2.2 IntelliCenter Home Assistant integration

The root `intellicenter/` directory is the source of one Home Assistant custom integration.
It owns:

- Home Assistant setup and configuration flow
- Connection lifecycle and coordination with `pyintellicenter`
- Home Assistant entity platforms
- Integration diagnostics and translations
- Translation of the live Pentair model into immutable read snapshots

The complete directory is the deployable unit. When installation begins, it will be copied or
released as:

```text
/config/custom_components/intellicenter/
```

It is intentionally excluded from the PoolOS wheel.

### 2.3 IntelliCenter immutable API

`intellicenter/api/` is an internal, read-only package. It contains only immutable normalization
models and the snapshot facade used by the root integration.

Its canonical contents are:

```text
__init__.py
body.py
chemistry.py
circuit.py
cover.py
models.py
panel.py
pump.py
system.py
temperature.py
```

Home Assistant platform modules, manifests, translations, configuration flows, coordinators, and
project configuration files must not be duplicated beneath `intellicenter/api/`.

## 3. Runtime Safety Boundary

PoolOS currently performs:

```text
OBSERVE -> EVALUATE -> DECIDE -> EXPLAIN -> RECORD -> PUBLISH
```

Repository cleanup, integration preparation, and documentation changes must not silently cross
into live actuation.

Future command delivery must continue through explicit operation, validation, ownership, runtime
mode, safety, and vendor-delivery boundaries.

## 4. Layered Architecture

```text
Pentair IntelliCenter controller
            |
            v
      pyintellicenter
            |
            v
IntelliCenterCoordinator
            |
            v
Immutable IntelliCenter API
            |
            v
Home Assistant entity and observation layer
            |
            v
          PoolOS
  observe / evaluate / decide
  explain / record / publish
            |
            v
Vendor command-delivery boundary
      (actuation disabled)
```

The immutable IntelliCenter API reports equipment facts. PoolOS decides what should happen. The
future execution path will translate validated canonical operations into vendor commands without
allowing Home Assistant entities or policy code to bypass the delivery boundary.

### 4.1 Downstream operational-action boundary

Operational intelligence ends at one validated, immutable pipeline result. ADR-044 defines the
first downstream consumer as a vendor-neutral adapter contract:

```text
Operational Disposition
        |
        v
Operational Action Pipeline <-> Operational Action Registry
        |
        v
Validated OperationalActionPipelineResult
        |
        v
NonHardwareOperationalActionAdapter
        |
        +-- no action ----------> immutable no-op receipt
        +-- reevaluation -------> immutable deferred receipt
        +-- operator review ----> immutable accepted receipt
        +-- execution targets --> immutable rejected receipt
```

This first adapter emits deterministic evidence only. It does not invoke a scheduler, publish an
operator-review item, generate or mutate an execution plan, import vendor integrations, deliver a
command, or actuate equipment. Future downstream adapters require separate architectural and
safety review.

ADR-045 adds a dedicated consumer for deferred reevaluation receipts:

```text
Immutable deferred reevaluation receipt
        |
        v
ReevaluationScheduleRequest + explicit supplied time
        |
        v
DeterministicReevaluationScheduler
        |
        v
Immutable scheduled / rejected / duplicate / cancelled record
```

This scheduler is an in-memory recorder, not the execution-plan scheduler. It does not parse the
reevaluation hint, run a decision cycle, publish a runtime trigger, create a plan, or invoke any
external system. Persistence, due-request selection, and typed evaluation-trigger integration are
future reviewed boundaries.

ADR-046 adds pure due selection and typed trigger conversion:

```text
Immutable reevaluation schedule records + explicit as_of
        |
        v
DueReevaluationTriggerBoundary + prior completion evidence
        |
        +-- due ----------> EXPECTED_CHANGE_REACHED trigger request + completion ID
        +-- future -------> immutable not-due evidence
        +-- cancelled ----> immutable cancelled evidence
        +-- completed ----> immutable duplicate evidence
        +-- invalid ------> immutable rejected evidence
```

The boundary does not submit the typed request to the runtime. Trigger coalescing, evaluation
context construction, Decision Orchestrator invocation, persistence, and restart recovery remain
separate reviewed responsibilities.

## 5. Coordinator Responsibilities

`IntelliCenterCoordinator` owns communication lifecycle concerns:

- Controller connection and reconnection
- Live Pentair model synchronization
- Push-update processing
- Discovery of equipment objects
- Scheduling Home Assistant refreshes
- Exposing the authoritative controller and model to integration consumers

The coordinator must not contain PoolOS scheduling, ownership, safety, or operating policy.

## 6. Immutable Read Model

The immutable API must:

- Read from the coordinator's authoritative live model
- Return immutable snapshots instead of raw mutable controller objects
- Normalize Pentair-specific attributes and values
- Preserve unknown, unavailable, and unsupported states explicitly
- Expose stable identifiers independent of Home Assistant entity IDs
- Remain free of scheduling and operational policy
- Remain command-free

## 7. Home Assistant Entity Layer

Home Assistant entities are presentation and interaction adapters. They should:

- Read through immutable models where available
- Translate immutable models into Home Assistant entity properties
- Avoid embedding PoolOS policy
- Avoid restoring stale state snapshots
- Preserve stable entity identifiers and behavior when practical

User-initiated entity commands may remain part of the hardware integration, but automatic PoolOS
commands must eventually pass through the canonical command-delivery path.

## 8. Packaging and Distribution

The root `pyproject.toml` packages only `poolos*`.

This is intentional:

- `pip install poolos` installs the vendor-independent Python package.
- It does not install the Home Assistant custom integration.
- IntelliCenter deployment will use a complete custom-component directory or a future HACS
  release package.

The repository must document both installation paths before public release.

## 9. Static Analysis Boundary

Required repository checks are:

```text
compileall: poolos and intellicenter
Ruff:      poolos, intellicenter, and tests
MyPy:      poolos
pytest:    complete test suite
```

MyPy is currently limited to the installable PoolOS package because the Home Assistant integration
has separate external runtime and typing dependencies. This boundary is intentional but must stay
visible in documentation and CI.

A future integration milestone may add a Home Assistant-aware MyPy or import-validation job.

## 10. Restart Safety

After a future Home Assistant or integration restart:

- The coordinator reconnects and rebuilds authoritative equipment state.
- The immutable API exposes a new snapshot.
- PoolOS rebuilds an evaluation context from current observations.
- Safety and ownership are reevaluated from current facts.
- No stale pre-restart command or equipment snapshot is blindly restored.

## 11. Observability

The combined system should expose diagnostic information for:

- Current observations and freshness
- Current operating mode
- Active safety reason
- Current owner by equipment function
- Decision alternatives and selected plan
- Last evaluation time and trigger
- Last proposed or delivered command and result
- Suppressed duplicate or unsafe commands
- Controller and publication availability

Diagnostics must not expose secrets or authentication material.

## 12. Testing Strategy

Testing remains layered:

1. IntelliCenter immutable read-model unit tests
2. IntelliCenter repository-structure and contract tests
3. PoolOS domain and observation tests
4. Policy, planning, and decision tests
5. Runtime, recovery, and replay tests
6. Golden end-to-end scenarios
7. Home Assistant runtime validation before integration release
8. Staged command-delivery tests before any live automatic actuation

A green unit-test suite does not by itself establish that a Home Assistant package is deployment
ready.

## 13. Deployment Strategy

Git is the development source of truth. Home Assistant is a deployment target.

The IntelliCenter integration is not installed in Home Assistant yet. Until its installation
milestone:

- Changes are made and validated in this repository.
- Complete coherent changes are committed and pushed to the private GitHub repository.
- The root IntelliCenter directory remains one future deployable custom component.
- No partial integration files are copied into Home Assistant.
- Public GitHub or HACS distribution is deferred until licensing, metadata, installation,
  upgrade, and runtime validation are complete.
