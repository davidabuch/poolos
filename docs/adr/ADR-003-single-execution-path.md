# ADR-003: Use a Single Execution Engine for Command Center Writes

- Status: Accepted
- Date: 2026-07-24

## Context

Multiple components may eventually request equipment changes: schedules, safety logic, manual Command Center actions, heating logic, and power management. Allowing each component to call the Pentair controller directly would create conflicting commands, inconsistent safety checks, and poor observability.

## Decision

The Execution Engine will be the only Command Center component allowed to send commands to the Pentair controller.

All Command Center requests, including manual actions initiated through the Command Center, must produce desired state or an equivalent typed request and flow through the Execution Engine and Command Dispatcher.

Existing Home Assistant entity command methods may remain during migration, but new Command Center code must not create another direct write path.

## Consequences

### Positive

- One audited command path
- Central ownership enforcement
- Command deduplication
- Deterministic ordering
- Consistent retries and error handling
- Better diagnostics and flight recording
- Easier idempotency testing

### Negative

- Execution Engine becomes critical infrastructure
- Manual requests may require additional modeling
- Migration from existing direct entity writes must be staged carefully

## Rejected alternatives

### Permit every manager to send its own commands

Rejected because it creates race conditions and duplicated safety logic.

### Send commands directly from the Decision Engine

Rejected because decision calculation should remain pure and testable.
