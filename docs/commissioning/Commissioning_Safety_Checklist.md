# PoolOS Commissioning Safety Checklist

Use this checklist before every operating-mode advancement. A checked item must
be supported by current evidence, not assumption.

## Universal Requirements

- [ ] Current operating mode is visible and correct.
- [ ] Requested target mode is explicit.
- [ ] Operator approval is recorded for the requested advancement.
- [ ] Required observations are mapped to the correct physical equipment.
- [ ] Required observations are available, fresh, and unit-correct.
- [ ] Contradictory or unknown evidence fails closed.
- [ ] Flight Recorder is healthy and writing complete evidence.
- [ ] Restart behavior has been tested for the current mode.
- [ ] Manual IntelliCenter panel and application changes are observed correctly.
- [ ] Human override and ownership behavior are understood.
- [ ] Rollback to `OBSERVE` has been tested.
- [ ] Native safety features remain operational unless formally replaced.
- [ ] Known limitations and unresolved anomalies are documented.

## Before LEARN

- [ ] Observation coverage is continuous over a representative period.
- [ ] Data gaps and unavailable entities are identifiable.
- [ ] Learning outputs expose evidence window, derivation, freshness, and confidence.
- [ ] Learned values cannot alter control policy silently.

## Before ADVISE

- [ ] Recommendations identify reasons, assumptions, blockers, and expected outcomes.
- [ ] Recommendations clearly distinguish current behavior from proposed behavior.
- [ ] Uncertainty and stale evidence are visible.
- [ ] Operators can inspect supporting evidence.

## Before SHADOW

- [ ] Complete hypothetical service calls are generated without delivery.
- [ ] Expected observations and verification windows are defined.
- [ ] Shadow plans preserve deterministic identity and provenance.
- [ ] Representative success and failure scenarios have been reviewed.
- [ ] No transport credential or configuration can bypass shadow blocking.

## Before ASSIST

Complete this section separately for each capability.

- [ ] Capability name and equipment scope are documented.
- [ ] Capability is explicitly approved by the operator.
- [ ] Capability has a visible armed state.
- [ ] Capability has a narrow ownership boundary.
- [ ] Preflight safety checks are defined and tested.
- [ ] Post-delivery observation verification is required.
- [ ] Failure, timeout, mismatch, and unavailable behavior are tested.
- [ ] Immediate capability rollback is tested.
- [ ] Manual recovery procedure is documented.
- [ ] Conflicting schedules and automations are identified.

## Before CONTROL

- [ ] All controlled capabilities completed assisted commissioning.
- [ ] No unexplained command, verification, or recovery behavior remains.
- [ ] Long-running observation and shadow evidence is satisfactory.
- [ ] Assisted operation has covered representative operating conditions.
- [ ] Ownership transfer and manual override behavior are tested.
- [ ] Safety regression and restart tests are complete.
- [ ] Conflicting native schedules or automations are retired deliberately.
- [ ] Full-system rollback to `OBSERVE` is tested.
- [ ] Operator explicitly approves CONTROL mode and its capability scope.

## Automatic Regression Triggers

PoolOS should reduce authority or block action when any applicable condition is
present:

- [ ] Required observation unavailable or stale.
- [ ] Contradictory evidence or identity mismatch.
- [ ] Flight Recorder or required diagnostics unhealthy.
- [ ] Ownership cannot be established safely.
- [ ] Verification repeatedly fails or times out.
- [ ] Safety posture is unknown or blocked.
- [ ] Restart recovery cannot reconstruct valid current state.
- [ ] Operator requests rollback.

Automatic regression never authorizes automatic re-advancement. New operator
approval is required after health and readiness are restored.
