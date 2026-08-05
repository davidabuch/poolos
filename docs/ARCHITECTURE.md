# PoolOS Architecture Manual

The PoolOS Architecture Manual is the canonical conceptual reference for the project. It explains why the system exists, how responsibilities are divided, and which architectural rules future changes must preserve.

## Start here

1. [Executive Overview](architecture/00-executive-overview.md)
2. [Design Philosophy](architecture/01-design-philosophy.md)
3. [Guiding Principles](architecture/02-guiding-principles.md)
4. [Capability Map](architecture/03-capability-map.md)
5. [System Layers](architecture/04-system-layers.md)
6. [Dependency Rules](architecture/05-dependency-rules.md)
7. [Data Flow](architecture/06-data-flow.md)
8. [Canonical Identity Model](architecture/07-canonical-identity-model.md)

## Planned chapters

- Safety model
- Observation layer
- Cognitive system
- Supervisory runtime
- Execution system
- Integration layer
- Package guide
- Terminology
- How PoolOS thinks

## Related references

- [Public API Policy](PUBLIC_API.md)
- [Development Roadmap](ROADMAP.md)
- [Architecture Decision Records](adr/)

## Document roles

- The Architecture Manual explains the enduring conceptual design.
- ADRs record specific decisions and their consequences.
- The roadmap records sequencing and implementation status.
- The public API policy defines supported import behavior.
- Source code and tests implement and enforce the design.

## Change policy

Material architecture changes should update the relevant manual chapter and add or amend an ADR when a concrete design decision changes.
