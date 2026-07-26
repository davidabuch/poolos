# PoolOS Equipment Model

Equipment represents physical pool hardware. Vendor adapters map real devices
to PoolOS equipment and capabilities.

Initial categories include pumps, heaters, filters, valves, lights,
chlorinators, blowers, cleaners, covers, and sensors.

## Capabilities

Applications depend on capabilities rather than brands or model numbers. A
variable-speed pump may advertise start/stop, RPM control, RPM sensing, power
monitoring, and fault reporting. A single-speed pump may advertise only
start/stop and fault reporting.

## Filters

Filters are first-class equipment because they have identity, media, size,
maintenance history, and health trends. Instrumentation is optional.

An analog pressure gauge is not readable by PoolOS. Therefore:

- digital pressure is absent unless a pressure transducer or adapter supplies it;
- flow is absent unless a flow sensor supplies it;
- learned filter health may still use runtime, pump power, priming behavior,
  heater flow faults, maintenance events, and calibrated clean-filter baselines;
- every estimate includes confidence and supporting evidence.

PoolOS must never invent PSI from an analog gauge.
