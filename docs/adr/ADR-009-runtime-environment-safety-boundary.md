# ADR-009: Runtime Environment Safety Boundary

- Status: Accepted
- Date: 2026-07-29

## Context

PoolOS must run the same planning and operation pipeline in three materially
different environments:

- simulation, where commands may affect only a digital twin;
- shadow, where real observations are evaluated but physical commands are only
  recorded as recommendations;
- live, where explicitly approved physical endpoints may receive commands.

A mutable boolean such as `simulation=True` is not a sufficient safety boundary.
It encourages repeated conditional checks and permits a live endpoint to be
accidentally registered alongside a simulator.

The simulation will eventually consume selected live Home Assistant sensors.
Observation access must therefore be independent from command-delivery access.
Reading a real roof or water-temperature sensor in simulation must not imply
permission to control real equipment.

## Decision

PoolOS will construct an immutable `PoolRuntimeEnvironment` at startup.

The environment contains:

- one `RuntimeMode`;
- one stable installation identity;
- one clock;
- an observation-source allow-list;
- a delivery safety policy;
- a validated tuple of writable endpoints.

Writable endpoints declare one safety classification:

- `SIMULATOR` — in-memory or digital-twin delivery;
- `SHADOW` — records a command without physical delivery;
- `PHYSICAL` — can affect real equipment.

The permitted combinations are:

| Runtime mode | Permitted endpoint kind | Physical delivery |
|---|---|---|
| Simulation | Simulator | No |
| Shadow | Shadow | No |
| Live | Physical | Yes |

The environment rejects mixed or incompatible endpoint composition before an
`EndpointRegistry` can be built. The runtime mode and policies are immutable
after construction.

Observation provenance is validated separately. A simulation environment may
read approved live observations while all writable endpoints remain simulated.
This supports a hybrid digital twin without weakening the delivery boundary.

## Temperature treatment in hybrid simulation

Actual water temperature and simulated water temperature remain separate facts.
The actual sensor may initialize or calibrate the digital twin. Simulated water
temperature then evolves in response to simulated circulation, heating, solar
gain, and heat loss. Continuous replacement of simulated temperature with the
actual sensor would erase the effect of simulated commands.

## Consequences

### Positive

- Simulation cannot accidentally register the physical Home Assistant/Pentair
  endpoint.
- Shadow mode can evaluate real observations without physical writes.
- Live control requires explicit startup composition.
- Observation and command permissions remain independent.
- The same planner and operation pipeline can be used in all modes.

### Costs

- Every writable endpoint must declare its delivery classification.
- Startup composition must construct the appropriate environment explicitly.
- Shadow recording requires a dedicated shadow endpoint in a later milestone.

## Deferred work

This ADR does not yet implement:

- typed observation values and freshness;
- Home Assistant observation ingestion;
- a shadow recording endpoint;
- persistence of simulated state;
- Home Assistant publication or dashboard entities;
- live-control activation.
