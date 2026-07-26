# PoolOS

**A vendor-independent operating system for intelligent pool and spa control.**

PoolOS provides a deterministic control runtime, authority and safety layers,
constraint evaluation, planning, scheduling, execution, verification,
reconciliation, runtime memory, and explainability.

PoolOS is intentionally focused on pool and spa equipment. Home Assistant,
mobile apps, voice assistants, weather services, utility pricing, and battery
systems can provide commands or context without becoming competing controllers.

## Current milestone

`poolos-core-1.0` marks completion of the runtime kernel. Phase 2 defines the
pool domain model, hardware abstraction layer, vendor adapters, and native pool
applications.

## Architecture

```text
Intent -> Authority -> Constraints -> Planning -> Scheduling
       -> Execution -> Verification -> Reconciliation -> Memory
```

PoolOS models bodies, pool systems, equipment, hydraulic routes, features,
resources, and observations. Information is explicitly classified as measured,
calculated, learned, or predicted, with confidence and explainable evidence.

## Legacy IntelliCenter integration

The repository may also contain the existing Home Assistant IntelliCenter
integration. It will become the first vendor adapter while PoolOS remains
hardware-independent.

## Hardware abstraction

PoolOS includes a transport-independent hardware abstraction layer. Runtime and
applications target vendor-neutral equipment contracts; vendor adapters and
transports provide the implementation. Home Assistant and direct RS-485 are
supported architectural paths, but neither is a core dependency.

## Development

PoolOS uses `pyproject.toml` for packaging and development tools. The
recommended setup keeps dependencies isolated in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
python3 -m compileall poolos
python3 -m pytest
```

See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) for validation, coverage,
static analysis, CI, and troubleshooting instructions.

## Pentair vendor domain

PoolOS includes a transport-independent Pentair domain under
`poolos.vendors.pentair`. It models Pentair bodies, circuits, pumps, heaters,
valves, shared equipment, and heat selections without depending on Home
Assistant or direct RS-485 hardware. See
[`docs/PENTAIR_DOMAIN.md`](docs/PENTAIR_DOMAIN.md).
