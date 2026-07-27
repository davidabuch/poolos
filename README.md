# PoolOS

> **A deterministic automation platform for intelligent aquatic systems.**

[![CI](https://github.com/davidabuch/poolos/actions/workflows/tests.yml/badge.svg)](https://github.com/davidabuch/poolos/actions/workflows/tests.yml)

PoolOS is a vendor-independent operating system for swimming pool and spa automation.

Rather than embedding automation logic inside a specific controller, PoolOS separates **planning**, **decision making**, **execution**, and **hardware communication** into independent components. The result is a deterministic, testable, simulation-first automation platform capable of supporting multiple hardware vendors without changing application logic.

---

# Why PoolOS?

Traditional pool controllers tightly couple automation logic to proprietary hardware.

PoolOS takes a different approach.

Applications express **what should happen**.

PoolOS determines **how to accomplish it**.

Hardware adapters perform **vendor-specific execution**.

This architecture makes automation:

- Vendor independent
- Deterministic
- Fully testable
- Simulation capable
- Extensible
- Hardware agnostic

---

# Core Design Principles

✔ Hardware abstraction layer (HAL)

✔ Event-driven runtime

✔ Deterministic execution

✔ Simulation before deployment

✔ Strong domain model

✔ Vendor independence

✔ Test-first development

✔ Modern Python architecture

---

# Architecture

```text
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
        ┌─────────────┼─────────────┐
        │             │             │
    Pentair       Hayward      Simulation
        │             │             │
        └─────────────┼─────────────┘
                      │
                 Physical Equipment
```

PoolOS applications never communicate directly with vendor hardware.

Instead they interact with a stable hardware abstraction layer that isolates vendor-specific protocols from application logic.

---

# Current Capabilities

Current implementation includes:

- Runtime framework
- Event bus
- Scheduler
- Decision engine
- Execution engine
- Hardware abstraction layer
- Pentair domain model
- Simulation framework
- REST API foundation
- Configuration system
- Comprehensive automated testing
- Continuous Integration

---

# Repository Layout

```text
poolos/
    Core framework

intellicenter/
    Pentair IntelliCenter implementation

tests/
    Unit and integration tests

docs/
    Project documentation

examples/
    Example applications
```

---

# Development

Clone the repository

```bash
git clone https://github.com/davidabuch/poolos.git
cd poolos
```

Create a virtual environment

```bash
python3.13 -m venv .venv
source .venv/bin/activate
```

Install development dependencies

```bash
pip install -e ".[dev]"
```

Run the validation suite

```bash
python -m compileall poolos intellicenter

python -m ruff check poolos intellicenter tests

python -m pytest
```

---

# Project Status

Current development milestone

| Component | Status |
|-----------|--------|
| Runtime | ✅ |
| Event Bus | ✅ |
| Scheduler | ✅ |
| Decision Engine | ✅ |
| Execution Engine | ✅ |
| HAL | ✅ |
| Pentair Domain | ✅ |
| CI/CD | ✅ |
| Pentair Translation Layer | 🚧 |
| Home Assistant Transport | 🚧 |
| First Production Controller | 🚧 |

---

# Roadmap

Near-term objectives

1. Pentair translation layer
2. Home Assistant transport
3. Configuration engine
4. Production command center
5. First complete hardware deployment

Long-term vision

- Multiple controller vendors
- Intelligent optimization engine
- Digital twin simulation
- Predictive equipment maintenance
- Energy optimization
- Water chemistry optimization

---

# Philosophy

PoolOS treats swimming pool automation as an operating system problem rather than a controller problem.

Applications define desired outcomes.

The operating system plans execution.

Hardware adapters translate those plans into vendor-specific commands.

This separation enables sophisticated automation while remaining independent of any single manufacturer.

---

# Contributing

Contributions are welcome.

Please ensure all changes satisfy:

```bash
python -m compileall poolos intellicenter
python -m ruff check poolos intellicenter tests
python -m pytest
```

before submitting a pull request.

---

# License

See the LICENSE file for licensing information.