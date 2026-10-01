# PoolOS Operator Handbook

## What PoolOS is

PoolOS is the active pool and spa controller for its commissioned domains. It observes native
controller state, evaluates policy, manages scoped ownership, issues eligible commands, verifies
physical consequences, and records evidence.

It is not governed by one global "CONTROL" switch. Physical authority is intentionally split by
domain so one subsystem can be live while another remains disabled or advisory.

## Operating status

The **Operating Mode** diagnostic reports the current control profile:

| Profile | Meaning |
|---|---|
| `SCOPED_LIVE` | Command transport is available and one or more autonomous control domains are enabled |
| `MANUAL_CONTROL` | Command transport is available, autonomous domains are disabled |
| `OBSERVE_ONLY` | No physical command-delivery transport is available |

The profile is descriptive. Use the individual domain gates to understand or change authority.

## Main control gates

- **Automatic Filtration Execution** — permits automatic filtration purposes.
- **Automatic Thermal Execution** — permits the automatic thermal driver.
- **Thermal Live Execution** — permits physical thermal delivery; both thermal gates are required for autonomous thermal control.
- **Grid Outage Physical Safety** — permits reduction-only confirmed-outage protection.
- **Pool / Hot Tub Sanitation** — operator-started bounded maintenance sessions.
- **PoolOS Maintenance Mode** — global PoolOS physical-command deny.

A switch being ON does not guarantee a command will be issued. Current evidence, ownership,
policy, safety, transport readiness, and verification rules still apply.

## Why PoolOS has not acted

Common reasons include:

- the relevant scoped gate is OFF;
- Maintenance Mode is ON;
- required evidence is missing, stale, unavailable, or contradictory;
- an intentional operator action owns or restrains the affected domain;
- controller mode or topology is incompatible;
- a safety or policy rule blocks the action;
- a prior command is still awaiting authoritative verification;
- the current policy simply does not require action.

Use the Operations Center diagnostics and reason codes rather than inferring from equipment state alone.

## Human override

Manual operation is respected according to the ownership contracts. PoolOS must not treat every
physical mismatch as operator intent. Positive intentional operator control can preempt the
affected domain; unrelated domains should remain autonomous where safe.

A manual OFF can cancel the current session without permanently disabling future PoolOS policy.

## Maintenance Mode

Use **PoolOS Maintenance Mode** when PoolOS must be prevented from issuing physical commands
globally while observation continues.

After enabling Maintenance Mode:

- confirm the switch is ON;
- verify no new PoolOS physical delivery is permitted;
- leave native/manual controller access available;
- diagnose the underlying issue before clearing the deny.

Clearing Maintenance Mode restores eligibility, not stale ownership or stale commands.

## Reset PoolOS Control

**Reset PoolOS Control** creates a new authority epoch and drives a verified safe baseline for
PoolOS-owned control state. It is a recovery tool, not a routine mode selector.

Use it only when a reset of PoolOS authority/session state is intentionally required.

## Understanding command status

PoolOS separates:

1. **eligible / authorized** — policy and authority permit the command;
2. **accepted** — the transport accepted the exact command;
3. **observed** — later authoritative evidence arrived;
4. **verified** — physical state matches the expected result;
5. **converged / handed back** — the purpose completed safely.

Accepted delivery alone is not physical success.

## Restart behavior

A restart does not fabricate operator intent or reconstruct arbitrary stale authority. PoolOS may
restore only specifically supported durable intent or bounded recovery state, and otherwise
requires fresh authoritative evidence and legitimate acquisition boundaries.

After a restart verify:

- Observation Health;
- Operating Mode / control profile;
- domain gates;
- ownership diagnostics;
- current Pool/Spa topology and pump state;
- any pending cleanup/recovery state.

## Recommendations and retrospectives

Recommendations, behavioral inference, daily retrospective analysis, and similar intelligence
surfaces are advisory/read-only unless a separate production executor explicitly owns the action.
Their presence does not imply equipment authority.

## Operator responsibilities

The operator remains responsible for:

- deciding which scoped capabilities are enabled;
- preserving native safety systems unless formally replaced;
- reviewing unresolved physical anomalies;
- testing manual recovery and Maintenance Mode;
- validating equipment changes after controller/firmware/hardware changes;
- physically commissioning newly expanded authority.
