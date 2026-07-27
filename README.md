# PoolOS

> A vendor-independent automation platform for intelligent swimming pool and spa control.

![CI](https://github.com/davidabuch/poolos/actions/workflows/tests.yml/badge.svg)

PoolOS is a deterministic automation platform that separates automation logic from hardware. Applications define *what* should happen, while PoolOS determines *how* to execute those actions through vendor-specific adapters.

## Features

- Vendor-independent architecture
- Hardware Abstraction Layer (HAL)
- Deterministic execution engine
- Simulation-first development
- Event-driven runtime
- Comprehensive automated testing
- GitHub Actions CI

## Architecture

```
Applications
      │
      ▼
Decision Engine
      │
      ▼
Execution Engine
      │
      ▼
Hardware Abstraction Layer
      │
      ├── Pentair
      ├── Future Vendors
      └── Simulation
```

## Repository Structure

```text
poolos/           Core framework
intellicenter/    Pentair implementation
tests/            Automated tests
docs/             Project documentation
examples/         Example applications
```

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
pip install -e ".[dev]"
```

Validate the project:

```bash
python -m compileall poolos intellicenter
python -m ruff check poolos intellicenter tests
python -m pytest
```

## Current Status

| Component | Status |
|----------|:------:|
| Runtime | ✅ |
| Event Bus | ✅ |
| Scheduler | ✅ |
| Decision Engine | ✅ |
| Execution Engine | ✅ |
| Hardware Abstraction Layer | ✅ |
| Pentair Domain Model | ✅ |
| Continuous Integration | ✅ |
| Pentair Translation Layer | 🚧 |
| Home Assistant Integration | 🚧 |

## Roadmap

Near-term priorities:

- Pentair translation layer
- Home Assistant transport
- Configuration engine
- Production command center

## Philosophy

PoolOS treats pool automation as an operating system problem rather than a controller problem. By separating planning, execution, and hardware communication, automation logic becomes portable, testable, and independent of any specific manufacturer.

## Contributing

Before submitting changes, ensure the repository passes all validation checks:

```bash
python -m compileall poolos intellicenter
python -m ruff check poolos intellicenter tests
python -m pytest
```

## License

See the `LICENSE` file for licensing information.