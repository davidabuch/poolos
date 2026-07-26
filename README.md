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
