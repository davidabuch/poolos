# PoolOS Control Authority Framework

Milestone 9.2 introduces deterministic control-source resolution before commands
reach the Execution Engine.

## Core rule

Home Assistant is a PoolOS user interface. A Home Assistant action emits a
normal `Command` with `metadata["control_source_id"] = "home_assistant"`.
It does not directly own hardware and does not automatically create a manual
override.

## Authority order

1. Service mode owns all scopes for its service source.
2. A scoped local-panel/manual lease owns its exact target or namespace.
3. Otherwise PoolOS automatic and registered UI commands are allowed.
4. Safety constraints are deliberately separate and will be added in 9.3.

## Scope matching

A lease for `pump.main` covers `pump.main` and children such as
`pump.main.speed`, but not `pump.secondary`. More-specific matching leases win.

## Command source metadata

The source is resolved from `command.metadata["control_source_id"]`, falling
back to `command.requested_by`. Unknown sources are denied and audited.

## Events

The framework publishes acquisition, release, expiration, service-mode, and
command-denial events through the kernel event bus.
