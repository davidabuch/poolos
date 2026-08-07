# PoolOS

> A vendor-independent automation platform for intelligent swimming pool and spa control.

![CI](https://github.com/davidabuch/poolos/actions/workflows/tests.yml/badge.svg)

PoolOS is a deterministic automation platform that separates automation policy from hardware.
Applications define *what* should happen, while PoolOS determines *how* to evaluate, explain,
record, publish, and eventually deliver those actions through vendor-specific boundaries.

PoolOS currently stops before live automatic actuation. Its production safety boundary is:

```text
OBSERVE -> EVALUATE -> DECIDE -> EXPLAIN -> RECORD -> PUBLISH
```

## Features

- Vendor-independent architecture
- Canonical typed observation framework
- Durable transition/checkpoint observation history for behavioral analysis
- Behavioral inference with explicit confidence and raw-evidence provenance
- Deterministic decision and planning layers
- Runtime-mode safety boundary
- Simulation-first development
- Decision explanations and flight recording
- Restart recovery and deterministic replay
- Home Assistant observation and publication boundaries
- Comprehensive automated testing
- GitHub Actions continuous integration

## Architecture

```text
Home Assistant and vendor observations
                 |
                 v
              PoolOS
                 |
      observe / evaluate / decide
       explain / record / publish
                 |
                 v
     Command-delivery boundary
        (live actuation disabled)
```

## Repository Structure

```text
poolos/                     Installable vendor-independent PoolOS package
intellicenter/              Pentair IntelliCenter Home Assistant integration source
intellicenter/api/          Immutable internal IntelliCenter read-model package
tests/                      PoolOS and IntelliCenter read-model tests
docs/                       Architecture, development, roadmap, and ADRs
config/                     Example installation configuration
```

The repository root and the nested `poolos/` Python package intentionally share the same name.
They are not accidental duplicates.

The root `intellicenter/` directory is a future Home Assistant custom integration. It is not
included in the PoolOS Python distribution. When deployment begins, the complete directory will
be installed as:

```text
/config/custom_components/intellicenter/
```

See `docs/INTELLICENTER_DEPLOYMENT.md` for the planned deployment boundary.

## Development

Clone the repository:

```bash
git clone https://github.com/davidabuch/poolos.git
cd poolos
```

Create a virtual environment:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Validate the project:

```bash
python -m compileall poolos intellicenter
python -m ruff check poolos intellicenter tests
python -m mypy poolos
python -m pytest
```

MyPy currently checks only the installable `poolos` package. The IntelliCenter integration is
still checked by compilation, Ruff, structural tests, and its read-model unit tests. A separate
Home Assistant-aware typing boundary may be added when integration deployment work begins.

## Current Status

| Component | Status |
|---|:---:|
| Runtime and event model | Complete |
| Typed observations | Complete |
| Decision intelligence | Complete |
| Planning and policy | Complete |
| Explanations and flight recorder | Complete |
| Restart recovery and replay | Complete |
| Runtime diagnostics and golden scenarios | Complete |
| Home Assistant observation/publication | Complete |
| Persistent observation/event history | Complete |
| IntelliCenter immutable read model | In development |
| IntelliCenter Home Assistant deployment | Not yet installed |
| Live automatic actuation | Disabled |

## Roadmap

The current roadmap is maintained in `docs/ROADMAP.md`.

Before live control is enabled, PoolOS must retain explicit command-delivery, runtime-mode,
ownership, safety, validation, and audit boundaries.

## Philosophy

PoolOS treats pool automation as an operating-system problem rather than a controller problem.
By separating observations, policy, planning, explanation, runtime state, and command delivery,
automation logic becomes portable, testable, and independent of any specific manufacturer.

## Contributing

Before submitting changes, ensure the repository passes all required validation checks:

```bash
python -m compileall poolos intellicenter
python -m ruff check poolos intellicenter tests
python -m mypy poolos
python -m pytest
```

Review `git diff` and confirm GitHub Actions is green before merging or deploying.

## License

PoolOS is currently marked proprietary while private development continues. No public-use license
has been granted yet. Licensing must be selected and documented before the repository is made
public or distributed through HACS.
