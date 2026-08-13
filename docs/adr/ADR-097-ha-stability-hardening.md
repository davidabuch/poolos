# ADR-097 — Home Assistant Stability Hardening

## Status

Accepted for PoolOS milestone 12.0C5.1 pending validation.

## Context

During Home Assistant commissioning, Core reported a blocking `Path.read_text()` / `open()` call on the main event loop while PoolOS constructed the sustained native parity commissioning store. The synchronous history load was initiated from `PoolOSCoordinator.__init__()` during `async_setup_entry()`. Although this warning did not prove PoolOS caused a wider Home Assistant API-unresponsive incident, PoolOS must not perform filesystem I/O or potentially large history reconstruction on Home Assistant's event loop.

The parity record path was already executed through `hass.async_add_executor_job()`, as were persistent observation/inference/retrospective operations and native inventory export. However, startup history loading remained synchronous, and each parity record redundantly recomputed the full retained summary twice. Shutdown observations also showed in-flight PoolOS callbacks, motivating an explicit unload barrier.

## Decision

1. `NativeParityCommissioningStore` supports deferred history loading. Its default behavior remains backward compatible for core/test callers, while the Home Assistant coordinator constructs it with `load_history=False`.
2. Home Assistant setup explicitly loads and summarizes retained parity history through `hass.async_add_executor_job()` before the coordinator's first refresh. No parity history filesystem access is initiated from `PoolOSCoordinator.__init__()`.
3. A parity record computes the post-append commissioning summary once, reuses it for persistence, and returns the same object.
4. Home Assistant lifecycle diagnostics reuse the coordinator's cached parity summary instead of recomputing the full retained history on the event loop.
5. Unload sets a terminal guard, removes the mapped-state listener, and waits for any active observation protected by the coordinator observation lock before platform unload and transport shutdown continue. New event-driven observations are rejected after unload begins.

## Safety invariants

This hardening milestone does not change observation authority, parity semantics, tolerance, transport protocol allowlists, entity mappings, command authority, command delivery, or physical delivery. Home Assistant observations remain authoritative. Native IntelliCenter remains shadow/read-only.

## Deployment rule

The hardened build must pass focused tests, the full pytest suite, Ruff, MyPy, `git diff --check`, and the production safety search before a single controlled Home Assistant deployment. After deployment, no unrelated integration or automation changes are permitted during the initial stability observation window.
