# ADR-101 — Finalized Command-Free Thermal and Flexible Operation Policy

## Status

Accepted for implementation review.

## Decision

PoolOS uses one command-free supervisory policy foundation over actual native
IntelliCenter state. HA, ICP, and OCP transitions are equally valid human spa
evidence. Current equipment reality wins after restart; persisted session hints
never replay stale actions or override an observed OFF state.

### Pool temperature and solar

Plumbing temperature becomes trusted during meaningful pool circulation. The
last trusted value remains reusable for 30 minutes after circulation stops.
When stale, PoolOS requests a 1500-RPM probe only if a thermal decision is
actionable. Probing lasts at least two minutes, uses a rolling one-minute
settling assessment that accepts smooth movement up to 2°F/minute, and fails
closed after five minutes.

Pool solar activation is immediate once trusted water, collector ≥90°F,
differential ≥7°F, target demand, permissions, mode, and predictive gate all
permit it. The obsolete ten-minute activation hold is removed. While active,
differential below 7°F and target satisfaction each have independent continuous
ten-minute shutdown debounce.

Pool modes are one mutually exclusive enum: Solar Only, Solar Preferred, or Gas
Only. Solar Only never authorizes gas. Solar Preferred authorizes gas fallback
and bypasses forecast suppression. Gas Only suppresses solar. A separate
persistent solar override bypasses only Solar Only's predictive gate, never
physical eligibility or hard permissions.

For Solar Only deficits greater than 5°F, the initial predictive gate accepts
at least four forecast highs ≥78°F across the next five days. Missing or stale
forecast falls back to physical rules.

### Spa

One spa-session tracker represents HA/ICP/OCP user sessions. User spa heat-up
uses gas immediately unless roof ≥130°F continuously for two minutes, and
switches back after two continuous minutes below 130°F. Reaching target latches
maintenance for the session. Maintenance uses solar at roof ≥120°F while close
to target, gas below 120°F, or gas when deficit exceeds 2°F and roof is below
130°F. Spa Gas Only suppresses all spa solar.

Opportunistic spa heating is optional, solar-only, debt-aware, and available
from 1 PM to 6 PM after two minutes at roof ≥130°F. Once active it continues to
120°F and enters an isolated pump-off spa hold after two minutes below 120°F.
It may resume before 6 PM, preserves spa mode from 6 PM to 10 PM, never probes
the pool during that hold, and never uses gas. Human spa ON immediately claims
the session; human OFF returns to opportunistic reevaluation.

### Filtration, TOU, and pump policy

Daily filtration targets are configurable trusted-temperature bands of
6/8/9/10/12 hours. Valid pool-routed circulation earns minute-for-minute credit
at 1500, 2600, 2900, or 3000 RPM. Spa routing earns none. Only confirmed grid-
outage conservation earns two-thirds credit at 1500 RPM. At most two daily debt
records persist and are repaid oldest-first.

TOU remains generic timezone-aware tariff data. Safety and explicit user demand
rank first, then perishable thermal opportunity, then price optimization, then
deferrable filtration. Known-good baselines are probe/outage 1500, filtration
2600, solar 2900, and gas 3000 RPM. They are not optimal values. Pump GPM is not
control evidence for this VS pump.

Autonomous pump transitions use one-minute minimum ON/OFF debounce. Human and
safety transitions override it.

### Permissions and native configuration

Solar Allowed and Gas Allowed change only from intentional user/configuration
evidence, never ordinary target/differential/session shutdown. A read-only
native configuration guard reports scoped conflicts for native Solar Preferred,
competing RPM assignments, and schedules; it never fights or rewrites Pentair.

## Safety boundary

Every assessment reports authority NONE and command delivery disabled.
Generated intents are recommendations through the existing
`minimum_pump_rpm` optimizer contract. No command, service call, vendor write,
socket, execution proposal, plan, dispatch, build, deployment, or autonomous RPM
experiment is introduced.
