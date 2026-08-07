# ADR-079: Operational Intent Arbitration

- **Status:** Accepted
- **Milestone:** 11.2B
- **Date:** 2026-08-06

## Context

PoolOS 11.2A introduced immutable operational intents but intentionally stopped at deterministic ordering. Multiple intents can be simultaneously valid, compatible, contradictory, expired, superseded, or lower priority than a safety requirement. The next layer needs to resolve those conditions without prematurely optimizing equipment operation or generating commands.

## Decision

Introduce `OperationalIntentArbitrator`, a deterministic and side-effect-free arbitration layer. Arbitration receives canonical intents plus an explicit timezone-aware evaluation time. Requested and active intents are eligible when their request time has arrived and they have not expired. Terminal lifecycle states are ineligible. An eligible intent may explicitly supersede a prior intent identity.

Eligible candidates are considered in the canonical 11.2A order: priority descending, request time ascending, then stable identity. A declarative `IntentArbitrationPolicy` defines mutually exclusive intent groups and directional suppression relationships. Compatible intents remain selected together; PoolOS does not force a single global winner.

The default policy treats pool heating and spa heating as mutually exclusive, treats maintenance and commissioning modes as mutually exclusive, allows freeze protection to suppress energy conservation, quiet hours, and scheduled operation, allows equipment protection to suppress energy conservation and schedules, and allows maintenance mode to suppress routine operational intents. Safety ordering remains inherited from the canonical priority model.

Every input receives an explainable disposition: selected, ineligible, superseded, or conflict-suppressed. Suppression and supersession identify the winning intent. Duplicate identities and naive evaluation timestamps fail closed.

## Consequences

- PoolOS can now derive a deterministic compatible active-intent set from simultaneous requests.
- Safety and protective intent precedence is explicit and auditable.
- Compatible intents such as circulation and solar preference can coexist.
- Conflict policy remains declarative and testable rather than embedded in execution code.
- Arbitration does not evaluate arbitrary criterion semantics; preconditions and constraints remain preserved evidence for later objective/decision layers.
- This milestone performs no pump optimization, objective synthesis, execution planning, recommendation publication, Home Assistant call, command delivery, or physical actuation.
