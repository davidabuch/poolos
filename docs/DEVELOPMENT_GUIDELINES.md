# Buch IntelliCenter Development Guidelines

## 1. Source of Truth

The local Git repository is the development source of truth. GitHub mirrors committed work and runs continuous integration. Home Assistant is a deployment target, not the primary editing environment.

Do not treat files copied from Home Assistant as newer merely because they have a later filesystem timestamp. Compare code and Git history.

## 2. Delivery Format

Changes should be delivered as complete files with exact destination paths.

For each change set:

1. Replace or add the complete files in the local repository.
2. Review changes in VS Code Source Control.
3. Run available tests.
4. Commit with a focused message.
5. Push to GitHub.
6. Confirm GitHub Actions passes.
7. Do not deploy partial files to Home Assistant unless explicitly designated as an emergency hotfix.

Patch files and repository ZIP replacement are not the normal workflow.

## 3. Work Item Naming

Use milestone work-item identifiers in documentation and commit descriptions where useful:

```text
M1-003 Migrate climate platform to immutable API
M2-005 Add execution reconciliation loop
M3-003 Implement power outage safety mode
```

A work item should be small enough to review and test as a coherent unit.

## 4. Code Boundaries

### Coordinator

The coordinator manages connection lifecycle and the authoritative live Pentair model. It must not implement scheduling or operating policy.

### Immutable API

The immutable API normalizes live-model state into stable, immutable models. It must not make operating decisions or send commands.

### Home Assistant entities

Entities adapt immutable models to Home Assistant. They must not contain Command Center policy.

### Command Center

The Command Center decides desired behavior. It must not bypass the Execution Engine when sending controller commands.

### Execution Engine

The Execution Engine is the sole Command Center write path to the Pentair controller. New Command Center code must not call raw controller command methods directly.

## 5. Immutable Model Rules

Public immutable models should:

- Use frozen dataclasses with slots where practical
- Use explicit optional values for unknown data
- Use string-backed enums for normalized states
- Avoid exposing raw `PoolObject` instances
- Avoid exposing mutable dictionaries or lists
- Preserve stable identifiers
- Be safe to retain for the duration of one evaluation cycle

Do not silently translate unknown values into `0`, `False`, `off`, or empty strings.

## 6. Entity Migration Rules

When migrating an entity platform:

1. Identify every raw coordinator-model read.
2. Map each read to an immutable API field.
3. Confirm the immutable model distinguishes unavailable and unsupported values.
4. Preserve existing unique IDs and entity naming.
5. Preserve device associations.
6. Preserve supported features unless a change is intentional and documented.
7. Keep service methods behaviorally compatible.
8. Add tests for API method names and model contracts.
9. Compile and import the platform under tests.
10. Do not deploy the platform alone if it requires supporting API changes not installed in Home Assistant.

## 7. Command Rules

Commands should be:

- Idempotent
- Deduplicated
- Capability-checked
- Ownership-checked
- Ordered when dependencies exist
- Logged with reason and outcome
- Retried only according to a defined policy

A desired state field must distinguish "leave unmanaged" from "turn off". Missing values must not accidentally generate off commands.

## 8. Safety Rules

Safety behavior must:

- Have higher priority than normal operation
- Be derived from current facts
- Be restart-safe
- Release ownership promptly when the condition clears
- Trigger a complete reevaluation after release
- Avoid stale snapshot restoration
- Fail toward predictable equipment behavior

Safety code should be testable without a live Pentair controller.

## 9. Pump-Speed Rules

Actual variable-speed pump telemetry is read from the actual RPM sensor exposed by the integration, currently:

```text
sensor.buch_family_vs_rpm
```

Pentair RPM number entities are configuration presets. Do not use them as proof of current pump speed.

Do not modify heater, solar, high-speed, spa, waterfall, or other RPM preset values unless a separate feature explicitly manages Pentair configuration.

## 10. Testing Requirements

Every change should use the strongest applicable checks.

Minimum repository checks:

```bash
python -m compileall intellicenter tests
python -m pytest
```

Additional checks should include, when practical:

- Import tests for each Home Assistant platform
- Contract tests for API methods used by entities
- Pure-function tests for decision rules
- Ownership priority tests
- Execution reconciliation tests
- Restart reconstruction tests
- Regression tests for reported bugs

A test that searches source text can guard a narrow contract temporarily, but behavioral tests are preferred.

## 11. Review Checklist

Before delivering a complete file, verify:

- Imports exist in the repository or declared dependencies
- Referenced methods exist with the expected signatures
- Optional values are handled safely
- Entity unique IDs are unchanged unless intentionally migrated
- Coordinator availability is respected
- No new direct raw-model dependency bypasses an existing immutable API model
- No Command Center write bypasses the Execution Engine
- Restart behavior does not depend on old in-memory state
- Duplicate commands are avoided
- Failure paths are logged and do not leave ownership stuck
- Tests cover the primary behavior and the reported regression

## 12. Documentation Rules

Update documentation in the same change set when code changes:

- A public or internal contract
- Ownership semantics
- Safety priority
- Operating-mode behavior
- Repository structure
- Deployment procedure
- A previously accepted architectural decision

Use an Architecture Decision Record for decisions that are difficult to reverse or affect multiple layers.

## 13. Commit Guidance

Prefer focused, imperative commit messages:

```text
Document Command Center architecture
Stabilize climate immutable API contract
Migrate sensor entities to immutable models
Add power outage safety evaluation
```

Avoid mixing unrelated refactoring, feature work, and deployment changes in one commit.

## 14. Deployment and Rollback

Before a full Home Assistant deployment:

- Confirm Git status is clean
- Confirm GitHub Actions passes
- Build the package from the committed repository state
- Back up the installed integration directory
- Replace the entire integration as one matching unit
- Restart Home Assistant
- Review logs before functional testing
- Verify critical entities and commands

Do not delete the rollback backup until the new version has completed an agreed observation period.
