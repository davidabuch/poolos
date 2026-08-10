# PoolOS Architecture Manual

> **Version 1.0** · Canonical conceptual reference for PoolOS

The manual explains why PoolOS exists, how responsibilities are divided, how evidence moves through the system, and which architectural rules future changes must preserve.

## Reading paths

- **New contributors:** read Chapters 1–4, then Chapters 9–13.
- **Architecture reviewers:** read Chapters 5–10 and the related ADRs.
- **Implementation work:** use Chapter 10 with the public API policy and defining-module imports.
- **Future design:** read Chapters 12–15 before proposing new terminology or architectural patterns.

## Chapters

1. [Executive Overview](architecture/00-executive-overview.md)
2. [Design Philosophy](architecture/01-design-philosophy.md)
3. [Guiding Principles](architecture/02-guiding-principles.md)
4. [Capability Map](architecture/03-capability-map.md)
5. [System Layers](architecture/04-system-layers.md)
6. [Dependency Rules](architecture/05-dependency-rules.md)
7. [Data Flow](architecture/06-data-flow.md)
8. [Canonical Identity Model](architecture/07-canonical-identity-model.md)
9. [Safety Model](architecture/08-safety-model.md)
10. [Repository and Module Guide](architecture/09-repository-and-module-guide.md)
11. [Public API Integration](architecture/10-public-api-integration.md)
12. [How PoolOS Thinks](architecture/11-how-poolos-thinks.md)
13. [Glossary and Terminology](architecture/12-glossary-and-terminology.md)
14. [Architectural Patterns](architecture/13-architectural-patterns.md)
15. [Future Evolution](architecture/14-future-evolution.md)

## Related references

- [Public API Policy](PUBLIC_API.md)
- [Development Roadmap](ROADMAP.md)
- [Observation Intelligence and Soak Quality](OBSERVATION_INTELLIGENCE.md)
- [Architecture Decision Records](adr/)

## Document roles

- The Architecture Manual explains the enduring conceptual design.
- ADRs record specific decisions and their consequences.
- The roadmap records sequencing and implementation status.
- The public API policy defines supported import behavior.
- Source code and tests implement and enforce the design.

## Editorial conventions

- **PoolOS** refers to the complete system.
- **Layer** describes an architectural responsibility boundary; **module** describes a source-code unit.
- **Decision** is command-free cognitive evidence; **execution** is authorized operational work.
- **Adapter** is the only boundary permitted to translate approved operations into platform-specific interaction.
- Terms defined in the glossary are canonical throughout project documentation and ADRs.

## Change policy

Material architecture changes should update the relevant chapter and add or amend an ADR when a concrete design decision changes. Editorial corrections may update the manual directly when they do not change architectural meaning.

Architecture Manual Version 1.0 was completed through AR-2A–AR-2E.
