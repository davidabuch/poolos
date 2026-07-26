# PoolOS State Reconciliation

Milestone 9.4 adds continuous desired-versus-actual verification to the PoolOS Runtime.

## Design rules

1. Reconciliation never executes hardware commands directly.
2. Only successfully executed commands create desired-state expectations.
3. Verification is target-specific and registered through normalized verifier functions.
4. Every retry re-enters the normal Runtime path through authority, constraints, and execution.
5. Retry attempts are bounded; exhausted drift becomes an auditable terminal outcome.
6. Restart-safe behavior begins with observation and comparison rather than indiscriminate command replay.

## Runtime path

```text
Command
  -> Authority
  -> Constraints
  -> Execution
  -> Reconciliation expectation
  -> Verification window
  -> Stable / Retry / Exhausted
```

## Verifiers

A verifier compares a command's desired state with normalized state in the kernel and returns a `VerificationObservation`.

Verifiers can be registered for an exact target or a namespace. Exact targets win. Among namespace registrations, the longest matching namespace wins.

```python
runtime.reconciliation.register_verifier(
    "pump.main.speed",
    verify_main_pump_speed,
    policy=VerificationPolicy(
        verification_delay=timedelta(seconds=5),
        retry_delay=timedelta(seconds=10),
        max_attempts=3,
    ),
)
```

## Outcomes

- `PENDING`: expectation exists but is not yet due.
- `STABLE`: actual state matches desired state.
- `RETRY`: drift remains and a bounded retry command was produced.
- `EXHAUSTED`: maximum verification attempts were reached.
- `UNOBSERVABLE`: the target no longer has a verifier.

## Drift categories

- expected
- manual
- constraint
- hardware
- communications
- unknown

These categories are diagnostic. They do not bypass authority or constraints.

## Retry identity

A retry is a new command with a new `command_id`. It preserves the original target, action, value, priority, requester, and correlation identifier. Metadata records:

- `reconciliation_expectation_id`
- `retry_of`
- `retry_attempt`

The retry is processed as a normal PoolOS command. Reconciliation never submits it directly to an adapter.

## Restart behavior

The engine is intentionally observation-first. A future persistence adapter can restore desired-state expectations, but Runtime must still rebuild normalized actual state before deciding whether any corrective command is necessary.
