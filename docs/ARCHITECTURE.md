# PoolOS Architecture Manual

This file is the entry point to the canonical PoolOS architecture documentation.

The manual explains the enduring system design. Architecture Decision Records in `docs/adr/` explain why individual decisions were made. Module and API documentation explain implementation details.

## Start Here

1. [00 — Executive Overview](architecture/00-executive-overview.md)
2. 01 — Design Philosophy *(planned)*
3. 02 — Guiding Principles *(planned)*
4. 03 — Capability Map *(planned)*
5. 04 — Layered Architecture *(planned)*
6. 05 — Dependency Rules *(planned)*
7. 06 — Data Flow *(planned)*
8. 07 — Identity Model *(planned)*
9. 08 — Safety Model *(planned)*
10. 09 — Observation Layer *(planned)*
11. 10 — Cognitive System *(planned)*
12. 11 — Supervisory Runtime *(planned)*
13. 12 — Execution System *(planned)*
14. 13 — Integration Layer *(planned)*
15. 14 — Package Guide *(planned)*
16. 15 — Public API — see [PUBLIC_API.md](PUBLIC_API.md)
17. 16 — ADR Index *(planned)*
18. 17 — Development Workflow *(planned)*

## Current Architectural Summary

PoolOS separates:

```text
Observation
    |
    v
Cognitive decision-making
    |
    v
Supervisory composition
    |
    v
Execution
    |
    v
Home Assistant and vendor integration
```

The cognitive system determines what should happen. The execution system determines how accepted intent may be carried out safely. Integration adapters translate vendor-independent operations into platform-specific communication.

Live automatic actuation remains disabled and must not bypass the explicit execution, safety, ownership, runtime-mode, and delivery boundaries.

## Related Documentation

- [Public API Policy](PUBLIC_API.md)
- [Development Roadmap](ROADMAP.md)
- [IntelliCenter Deployment Boundary](INTELLICENTER_DEPLOYMENT.md)
- [Architecture Decision Records](adr/)

## Documentation Authority

When documents disagree:

1. Accepted ADRs govern the specific decision they address.
2. The Architecture Manual governs the current conceptual model.
3. Public API policy governs supported import behavior.
4. The roadmap describes planned work and status, not architectural authority.
