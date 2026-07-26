# PoolOS Simulation Engine

The simulation engine is a deterministic, hardware-independent adapter and world model for developing PoolOS behavior without controlling a real pool.

## Responsibilities

- Own a forward-only simulation clock.
- Execute normalized PoolOS commands against simulated equipment.
- Maintain normalized kernel state.
- Model approximate heating, solar gain, and ambient heat exchange.
- Inject weather, grid, equipment-availability, and command events.
- Record immutable snapshots for replay and assertions.
- Run reusable scenarios without Home Assistant or vendor libraries.

## Level-one thermal model

The initial model intentionally favors repeatability over physical precision. Each body can be configured with:

- heater temperature gain per hour
- maximum solar gain per hour
- ambient exchange coefficient
- minimum and maximum modeled temperatures

Heating requires both active heating equipment and active circulation. Solar gain requires circulation. Grid loss makes simulated equipment unavailable and inactive; restoration returns it to its baseline availability but does not silently restart it.

## Example

```python
sim = Simulation.create(kernel, start_at=start)
sim.add_thermal_model(BodyThermalModel("spa", heater_gain_per_hour=8.0))
sim.submit(Command("spa_pump", CommandAction.START, issued_at=start))
sim.submit(Command("spa_heater", CommandAction.START, value=100.0, issued_at=start))
result = sim.advance(timedelta(hours=2))
```

The simulator is an execution adapter, not a policy bypass. Full operating-cycle tests should continue to route proposed commands through the Policy Engine and Execution Engine before the simulation adapter applies them.
