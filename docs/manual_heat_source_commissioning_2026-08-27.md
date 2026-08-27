# PoolOS Manual Heat-Source Control Commissioning

**Date:** 2026-08-27
**Status:** PASSED
**Scope:** Manual PoolOS heat-source selection for Pool and Hot Tub using native IntelliCenter authority.

## Software checkpoint

Branch:

`feature/native-solar-manual-control`

Heat-mode selector implementation commit:

`c21f015c4555f6228fb7b913191c84990dc64e53`

Commissioning ZIP SHA256:

`da81c66fdbc95df1cd5a371612c44b266f566bf319e94fc2a084defafc3d6aaf`

Home Assistant Core:

`2026.8.3`

## Safety model

PoolOS retains the control invariant:

**OBSERVE -> DECIDE -> COMMAND -> RE-OBSERVE -> CONFIRM**

Native IntelliCenter remains authoritative for controller-owned facts.

The manual heat-source command gateway is intentionally bounded to:

- Pool body: `B1101`
- Hot Tub body: `B1202`
- Off: `HEATER=00000`
- Gas: `HEATER=H0001`
- Solar: `HEATER=H0002`

Direct `HTMODE` writes are prohibited.

Pentair Solar Preferred is not used by this command surface.

## User-facing requested heat modes

PoolOS exposes the following requested modes for both Pool and Hot Tub:

- Off
- Solar
- Gas
- Solar Preferred

Defaults:

- Pool: `Solar`
- Hot Tub: `Solar Preferred`

`Solar Preferred` is a PoolOS policy intent, not a native Pentair heat-source selection.

PoolOS requested mode and effective native heat source are intentionally separate concepts.

## Native heat-source topology

Empirical IntelliCenter topology confirmed:

- Pool body: `B1101`
- Hot Tub body: `B1202`
- Gas heater: `H0001`
- Solar heater: `H0002`
- Native no-heater value: `00000`

Both `H0001` and `H0002` advertise availability to both `B1101` and `B1202`.

Pentair's separate Solar Preferred object is not part of the PoolOS manual command mapping.

## Native semantics

Empirical testing confirmed:

### Off

- `HEATER=00000`
- `HTMODE=0` when no heat source is operating

### Gas

- selected source: `HEATER=H0001`
- active heating state can report `HTMODE=1`

### Solar

- selected source: `HEATER=H0002`
- active heating state can report `HTMODE=2`

Important distinction:

**HEATER is selected-source truth.**

**HTMODE is operating/heating-state truth.**

A selected source may remain present in `HEATER` while `HTMODE=0` when there is no active heating demand.

This behavior was observed directly during both Pool and Hot Tub testing.

## Pool direct-mode commissioning

Initial state:

- Pool active: ON
- Hot Tub active: OFF
- Pool requested mode: Solar
- Native Pool HEATER: `H0002`
- Native parity issues: 0

The following transitions were commanded through:

`select.poolos_native_intellicenter_pool_heat_mode`

### Solar -> Off

Observed:

- requested mode: Off
- native `HEATER=00000`
- effective source: Off
- parity issues: 0

### Off -> Gas

Observed:

- requested mode: Gas
- native `HEATER=H0001`
- effective source: Gas
- parity issues: 0

### Gas -> Solar

Observed:

- requested mode: Solar
- native `HEATER=H0002`
- effective source: Solar
- parity issues: 0

Pool remained active throughout.

Hot Tub remained off throughout.

No RPM command was issued during this selector test.

No temperature setpoint was changed.

**Pool direct-mode commissioning result: PASSED**

## Hot Tub direct-mode commissioning

Initial state:

- Pool active: ON
- Hot Tub active: OFF
- Hot Tub requested mode: Solar Preferred
- native Hot Tub `HEATER=00000`
- parity issues: 0

PoolOS then activated the Hot Tub through the native PoolOS climate entity.

As expected for the shared-body hydraulic system:

- Hot Tub became active
- Pool became inactive during Hot Tub operation

The following transitions were commanded through:

`select.poolos_native_intellicenter_hot_tub_heat_mode`

### Off

Observed:

- requested mode: Off
- native `HEATER=00000`
- effective source: Off
- parity issues: 0

### Solar

Observed:

- requested mode: Solar
- native `HEATER=H0002`
- native `HTMODE=2`
- effective source: Solar
- parity issues: 0

### Gas

Observed:

- requested mode: Gas
- native `HEATER=H0001`
- native `HTMODE=1`
- effective source: Gas
- parity issues: 0

**Hot Tub direct-mode commissioning result: PASSED**

## PoolOS Solar Preferred semantics

After Hot Tub Gas was confirmed, the requested Hot Tub mode was changed to:

`Solar Preferred`

At that moment:

- requested mode became Solar Preferred
- native `HEATER` remained `H0001`
- effective source remained Gas
- Pentair Solar Preferred was not used
- autonomous Solar Preferred delivery remained disabled

Native `HEATER` was observed for 10 seconds after the PoolOS Solar Preferred selection and remained unchanged.

This confirms that PoolOS Solar Preferred is presently **intent only**.

It does not issue an immediate hidden native heat-source command.

PoolOS Solar Preferred must remain distinct from Pentair Solar Preferred.

## Hot Tub shutdown behavior

After commissioning:

- Hot Tub was commanded OFF
- Hot Tub active state returned OFF
- Pool automatically returned ON
- Hot Tub requested mode remained Solar Preferred
- native Hot Tub `HEATER` retained `H0001`
- Hot Tub `HTMODE` returned to `0`

The retained `HEATER=H0001` while Hot Tub is OFF further confirms that selected source and active heating state are separate concepts.

## Pool Solar + pump-speed commissioning

Prior live commissioning also established independent Pool Solar and pump-speed control.

Successful sequence:

1. Pool Solar OFF
2. Confirm native Solar OFF
3. Set Pool pump to 2600 RPM
4. Confirm actual pump RPM 2600
5. Hold Solar OFF + 2600 RPM for five minutes
6. Raise Pool pump to 2900 RPM
7. Confirm actual pump RPM 2900
8. Re-enable Pool Solar
9. Confirm native Solar ON

Parity issues remained 0.

This demonstrated that after removal of the Pentair Solar Speed configuration, PoolOS can independently control both Pool heat-source selection and Pool RPM while Solar is selected.

## Final restored operating state

At the conclusion of commissioning, PoolOS restored and confirmed:

- Pool: ON
- Pool requested heat mode: Solar
- Native Pool heat source: `H0002`
- Pool RPM setpoint: 2900 RPM
- Actual pump RPM: 2900 RPM
- Hot Tub: OFF
- Hot Tub requested heat mode: Solar Preferred
- Native parity issues: 0

## Commissioning conclusion

**PASSED**

The PoolOS manual heat-source control layer is commissioned for:

### Pool

- Off
- Gas
- Solar

### Hot Tub

- Off
- Gas
- Solar

The PoolOS requested-mode abstraction is also commissioned for:

- Pool default requested mode: Solar
- Hot Tub default requested mode: Solar Preferred

PoolOS Solar Preferred semantics are verified as separate from effective native heat-source state.

## Not yet commissioned

This commissioning does **not** authorize autonomous Solar Preferred actuation.

Pool and Hot Tub Solar Preferred must be developed as separate PoolOS policies.

Before autonomous delivery is enabled, each policy must define and validate:

1. authoritative temperature inputs;
2. heating-demand semantics;
3. solar physical-eligibility criteria;
4. activation thresholds;
5. shutdown thresholds;
6. hysteresis and debounce;
7. minimum runtime / minimum off-time as appropriate;
8. Pool versus Hot Tub priority;
9. gas fallback criteria;
10. pump-speed requirements and sequencing;
11. degraded/stale/unavailable-state behavior;
12. post-command re-observation and confirmation;
13. timeout and failure behavior;
14. restart/recovery behavior;
15. retained decision and execution evidence.

Autonomous Solar Preferred control must continue to follow:

**OBSERVE -> DECIDE -> COMMAND -> RE-OBSERVE -> CONFIRM**

and must fail toward observation/notification rather than unsafe actuation.
