# Sensor Platform Migration

## Status

M1-003 migrates Home Assistant sensor state reads to the immutable IntelliCenter API.
Raw `PoolObject` instances remain in use only for entity discovery, naming, and stable
unique IDs while dynamic equipment discovery is preserved.

## Immutable sources

- Physical probes: `TemperatureSensorState`
- Body last temperature: `BodyState.current_temperature`
- Pump measurements and limits: `PumpState`
- Chemistry measurements: `ChemistryState`
- Firmware and operating mode: `SystemState`

Actual pump speed is `PumpState.rpm`, which backs the existing VS RPM sensor. Pump
program setpoints remain configuration values and are not treated as actual speed.

## Compatibility requirements

The migration preserves existing entity names, unique IDs, units, device classes,
state classes, icons, categories, and dynamic discovery behavior. No files from this
repository milestone should be deployed individually to Home Assistant; deployment
occurs only after all entity platforms are migrated and repository tests pass.
