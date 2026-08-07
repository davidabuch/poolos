# ADR-080: Pump-operation optimization

## Status

Accepted for PoolOS milestone 11.2C.

## Decision

PoolOS will optimize pump RPM only after operational-intent arbitration. The optimizer consumes the already-selected canonical intents and an explicit installation-specific pump policy containing the valid RPM envelope, candidate step, and minimum RPM requirements associated with operational purposes.

The optimizer may also honor canonical intent constraints named `minimum_pump_rpm` and `maximum_pump_rpm`. It evaluates configured RPM candidates deterministically and recommends the lowest-energy feasible candidate. The energy index uses RPM cubed only as a monotonic affinity-law proxy for ranking pump-speed candidates; it is not represented as measured electrical power or a calibrated energy forecast.

If selected intents impose no pump requirement, the optimizer emits `no_operation_required`. If the effective minimum and maximum requirements cannot be satisfied by a configured candidate, it emits `infeasible` and deliberately produces no fallback RPM.

## Safety and authority boundary

11.2C produces a recommendation artifact only. It does not create a PoolOS command, execution plan, Home Assistant service call, vendor request, or physical actuation. Installation RPM values are policy inputs rather than hard-coded assumptions about Pentair equipment or the user's pool.

## Consequences

- pump selection is deterministic, explainable, replayable, and installation-specific;
- simultaneous compatible intents naturally combine by using the strictest effective minimum and maximum requirements;
- infeasible combinations fail closed rather than inventing an unsafe fallback;
- future learning can propose policy changes without silently changing the deterministic optimizer;
- publication of operator-facing recommendations remains milestone 11.2D.
