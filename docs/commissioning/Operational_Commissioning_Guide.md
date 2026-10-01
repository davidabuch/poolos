# PoolOS Operational Commissioning Guide

## Purpose

This guide defines how new PoolOS capabilities are introduced to real pool and spa
equipment. PoolOS no longer uses a global OBSERVE/LEARN/ADVISE/SHADOW/ASSIST/CONTROL
mode ladder in production. Authority is **domain-scoped**.

A capability becomes physically active only after its own evidence, ownership,
transport, policy, safety, and verification requirements are satisfied and the
operator explicitly enables the corresponding production gate.

## Current production control model

The top-level runtime profile is descriptive:

- `SCOPED_LIVE` — command transport is available and at least one autonomous
  physical-control domain is enabled;
- `MANUAL_CONTROL` — command transport is available but no autonomous domain is enabled;
- `OBSERVE_ONLY` — no physical command-delivery transport is available.

These are runtime descriptions, not a single authority selector.

Current production gates include:

- Automatic Filtration Execution;
- Automatic Thermal Execution;
- Thermal Live Execution;
- Grid Outage Physical Safety;
- Pool / Hot Tub sanitation sessions;
- PoolOS Maintenance Mode as a global physical-command deny.

Manual climate/equipment controls use the same command transport but remain subject to
physical-command authority, controller mode, and safety checks.

## Commissioning a new capability

### 1. Define the capability contract

Before physical work:

- name the exact equipment and authority domain;
- define positive operator intent and external-preemption semantics;
- define accepted evidence and currentness bounds;
- define command eligibility and fail-closed cases;
- define post-delivery verification;
- define termination, restart, and rollback behavior;
- add deterministic regression coverage.

### 2. Validate without physical authority

Use unit, integration, scenario, and CI validation first. Shadow/advisory engines may still
be used as non-authoritative analytical tools, but their existence does not define the
top-level PoolOS operating mode.

### 3. Enable only the new scoped gate

Do not broaden unrelated authority. Establish the live baseline immediately before
commissioning and identify STOP conditions.

### 4. Physically commission

For each commanded transition verify:

1. pre-command authoritative state;
2. exact accepted command;
3. later authoritative physical consequence;
4. correct ownership/provenance;
5. convergence or bounded failure;
6. safe termination / hand-back;
7. restart behavior when applicable.

A successful service/transport receipt is not physical success.

### 5. Preserve operator override

PoolOS yields only to positive intentional operator control, and only in the affected
domain where possible. Mismatch, unavailable evidence, or command failure do not by
themselves prove operator takeover.

### 6. Reacquire only at legitimate boundaries

Reevaluation alone does not create new ownership. Reacquisition requires a legitimate
new session, purpose, policy, or recovery boundary supported by current evidence.

## Rollback and global deny

For normal rollback, disable the affected scoped gate.

When a global PoolOS physical-command deny is required, enable **PoolOS Maintenance Mode**.
Maintenance Mode is the production replacement for the old conceptual instruction to
"return to OBSERVE." Observation and diagnostics continue while physical delivery is denied.

Reset PoolOS Control is a bounded recovery mechanism and must not be used as a substitute for
diagnosis or as a generic mode switch.

## Release evidence

Before a newly commissioned capability is treated as production-ready retain:

- regression tests;
- CI/Hassfest/HACS results where applicable;
- release/tag identity;
- loaded Home Assistant version;
- live system health;
- physical commissioning evidence;
- known residual edge cases;
- rollback path.

Repository tests, CI, deployed runtime, and physical commissioning are separate evidence levels.
