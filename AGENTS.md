# PoolOS Repository Constitution

## Scope and precedence

This file governs engineering work throughout the repository. Treat it as a durable safety and
workflow contract for humans and coding agents. More specific instructions may add constraints,
but must not weaken the safety, authority, evidence, or validation rules here.

Repository and runtime evidence outrank conversational memory. Inspect before assuming. If the
requested task conflicts with the repository, deployed behavior, or a safety boundary, stop and
report the contradiction rather than improvising.

## Core operating principles

- Protect physical equipment and people before optimizing convenience.
- Prefer the smallest coherent change over speculative refactoring.
- Review the actual diff; passing tests do not make an incoherent diff acceptable.
- Keep core PoolOS logic vendor-independent and Home Assistant-independent.
- Use narrow, immutable, typed contracts across architectural boundaries.
- Preserve identity, provenance, timestamps, reason codes, and explicit unknown values.
- Do not translate unknown evidence into `0`, `False`, `off`, or an empty value.
- Develop non-actuating behavior in simulation or shadow mode before considering live authority.

PoolOS equipment work follows this closed-loop sequence:

```text
observe -> decide -> command -> re-observe -> confirm
```

Do not continue dependent commands when an intermediate result is unconfirmed. Autonomous work
must fail closed when required evidence is stale, missing, contradictory, degraded, temporally
regressive, or otherwise insufficient.

## State, intent, and authority

Keep these concepts distinct in models, diagnostics, and tests:

- user-requested state;
- policy recommendation;
- planned state;
- native configured setpoint;
- command requested by PoolOS;
- command delivery result;
- observed actual equipment state;
- confirmed post-command state.

For pumps, separately represent requested or planned RPM, native configured RPM or setpoint, and
observed actual RPM. A configured Pool RPM may remain nonzero while the pump is physically off.
Never use a configured preset as proof of current pump operation.

Shadow or advisory output must not silently become live authority. Planning, readiness,
authorization, delivery, observation, and confirmation are separate stages. A valid plan is not
self-authorizing, adapter availability is not authorization, and entity availability is not a
safety decision.

Never broaden authority as a side effect of fixing planning, observability, diagnostics, or
availability. Authority increases require explicit scope, review, commissioning evidence, and
negative tests. Failures may reduce authority automatically; they must not increase it.

## Architecture and dependency boundaries

Dependencies point toward more foundational abstractions:

```text
canonical domain
  -> observations and environment
  -> policy and decision
  -> supervisory and operational routing
  -> execution
  -> delivery adapters
```

Runtime flow may proceed toward delivery, but vendor and platform details must not leak back into
core policy or domain models.

- Coordinators own connection lifecycle, authoritative live-model coordination, and publication.
  They must not become operating-policy engines.
- Immutable read APIs normalize mutable external models. They must not decide policy or issue
  commands.
- Home Assistant entities adapt published models for presentation and explicit user requests.
  They must not become a parallel automatic control engine.
- Core PoolOS owns vendor-neutral observations, policy, planning, decisions, explanations,
  execution contracts, and verification semantics.
- Delivery adapters translate an already-authorized canonical operation and return evidence. They
  must not invent goals, authority, plans, verification, or unrelated commands.
- Presentation and diagnostics must not mutate execution state or become a second source of truth.

Before adding an import or collaborator, identify which layer owns it, whether the dependency
points toward a foundation, whether immutable evidence is sufficient, and whether the behavior can
be tested without Home Assistant or physical equipment.

Use Architecture Decision Records for cross-layer or difficult-to-reverse decisions. Update the
architecture manual when enduring conceptual meaning changes; use the roadmap for status and
sequencing rather than putting temporary status in this constitution.

## Thermal and hydraulic safety

Treat all equipment-affecting behavior as safety-sensitive. Do not remove or bypass blockers merely
to make a planned operation executable.

Body activity, hydraulic route, valve position, selected heat source, actual heating state, and
pump speed are separate facts. Do not assume a body, valve, source, or RPM transition is safe merely
because policy recommends it. Configuration of a body is not proof that the body is active.

Preserve kill switches, commissioning scopes, authorization gates, ownership checks, freshness
checks, operation and equipment allowlists, verification deadlines, and recovery boundaries. Do
not issue a dependent step until authoritative evidence confirms the prior step. Do not invent a
compensating or restoration command unless a reviewed recovery policy explicitly authorizes it.

Any equipment-affecting change requires executable negative tests proving unsafe, stale,
unauthorized, out-of-scope, and unconfirmed commands are not delivered. Tests must use injected
fakes and must not contact Home Assistant, IntelliCenter, networks, or physical equipment.

## Home Assistant and event-loop rules

Avoid:

- blocking the Home Assistant event loop;
- recursive or self-triggering refresh loops;
- uncontrolled background tasks or unbounded task creation;
- competing refresh owners or state sources;
- heavy disk or network work on frequent coordinator paths;
- storage churn or unbounded write frequency;
- polling when reliable event-driven state is available;
- large, growing, or high-frequency Recorder attributes;
- state feedback loops caused by diagnostic entities.

Be explicit about coordinator refresh ownership and task cancellation on unload. Native publication
must not be delayed by unrelated durable work when the architecture provides separate publication
and persistence boundaries. Restart and reload behavior must be deterministic, leak-free, and must
not actuate equipment merely because state was restored.

Expose compact, bounded, sanitized diagnostics. Keep detailed history in its owned evidence store,
not in Home Assistant state attributes. Do not expose traceback-sized errors, credentials, network
addresses, tokens, or raw unbounded protocol data through entities.

## Temporal state and persistence

Stateful policy trackers must preserve chronological evidence. Do not weaken timestamp invariants to
silence regression errors. When multiple authoritative snapshots exist, never regress a tracker to
older evidence.

Repeated evaluation of the same observation must not double-count work. Refreshes must not invent
completed work, and stale evidence must not satisfy an obligation. Accumulated and daily accounting
must explicitly handle:

- restart and reload;
- persistence ownership and schema compatibility;
- midnight and day rollover;
- duplicate observations;
- out-of-order observations;
- retention and bounded growth;
- debt carry-forward where applicable.

Persist deterministic, versioned, privacy-safe evidence where replay matters. Reject malformed,
incompatible, duplicate, or inconsistent persisted state fail closed without breaking authoritative
observation processing. Avoid hidden mutable state and overlapping stores for the same ledger.

## Filtration principles

Filtration is an obligation, not merely a schedule. Deferral must not erase outstanding work, and a
scheduled interval is not proof that circulation occurred.

Credit filtration only from authoritative observations that satisfy the actual Pool filtration
policy. Do not credit Spa-only circulation as Pool filtration unless the policy explicitly supports
it. Preserve existing temperature bands, time-of-use rules, debt semantics, and ledger ownership
unless the task explicitly changes them.

Filtration observability should make required runtime, credited runtime, remaining runtime, current
disposition, running or deferral rationale, and the next suitable window auditable from
authoritative evidence. Do not create a second ledger when one authoritative ledger already exists.

## Solar and heat-source principles

Solar availability, Solar eligibility, selected policy mode, planned heat source, native selected
source, and actual heating are distinct. Favorable roof temperature alone does not authorize Solar;
rapid heat-up alone does not authorize Gas.

Respect user-use semantics, policy priority, target demand, source eligibility, hydraulic state,
safety evidence, and source-specific authorization. Preserve and test hysteresis, activation holds,
deactivation rules, and other stateful transitions. Prefer deterministic state machines over sleeps,
timing guesses, and polling workarounds. Avoid source chatter and never hide it by weakening
evidence or tolerances.

## Native IntelliCenter parity

Native IntelliCenter behavior is a major regression boundary. Before changing entity semantics,
units, availability, climate behavior, pump behavior, heat-source behavior, subscriptions, or state
interpretation, inspect the corresponding native behavior and the full acquisition-to-publication
path.

Do not normalize away meaningful distinctions among native setpoints, PoolOS plans, requested
values, and actual observations. Preserve proven read-only subscription and canonical-field
semantics. If PoolOS intentionally diverges from native behavior, document the reason and cover it
with behavioral tests.

Do not expose a general-purpose mutable IntelliCenter controller through a read boundary. Keep
vendor-specific query and command operations behind separate narrow adapters and explicit
allowlists. Read/query traffic is not equipment authority; command capability is not permission to
use it.

## Inspection before implementation

Before editing implementation code, inspect:

- the implementation and all relevant callers;
- behavioral and regression tests;
- state and timestamp ownership;
- persistence and retention ownership;
- entity exposure and Recorder impact;
- coordinator and event-loop flow;
- planning, authorization, command, and verification boundaries;
- relevant native-parity behavior;
- restart, unload, failure, and recovery paths.

Trace the actual data lifecycle rather than inferring behavior from class or function names. When a
live defect is involved, identify the first boundary where evidence becomes wrong or stops moving.
If evidence is insufficient or contradicts the requested design, stop and report it before making a
material architectural change.

## Change scope and editing practice

Make one bounded, reviewable change on a fresh feature branch based on current remote truth. Do not
reuse an old merged branch for unrelated work. Preserve unrelated user changes and stop if they
overlap the task.

Do not opportunistically refactor unrelated code, redesign architecture during a local fix, broaden
execution while fixing planning, or broaden authority while fixing observability. If correctness
requires a new architecture or authority grant, report that boundary instead of forcing it into the
task.

Use structured, reviewable patches. Do not make giant exact-string Python `.replace()` scripts the
normal editing method, and do not rely on brittle large-block source matching. Prefer portable
commands that work on macOS; do not assume GNU-only flags.

When giving interactive commands, label them `MAC TERMINAL` or `HOME ASSISTANT TERMINAL`. Do not
assume `/config` exists on macOS or that the local Git repository exists in the Home Assistant
terminal. Do not default user-facing interactive instructions to `set -eu`; provide readable checks
and explicit STOP conditions.

## Source truth and deployed truth

Repository source, GitHub state, deployment artifacts, and installed Home Assistant source are
separate truths. Do not infer one from another or infer deployed provenance from a matching version
number. Verify commit identity, artifact identity, and installed source independently when
provenance matters.

The repository is the development source of truth. Home Assistant is a deployment target, not the
primary editing environment. Do not treat a copied file as newer merely because its filesystem
timestamp is later.

## Development workflow

Use this sequence unless a task explicitly narrows it further:

```text
repository truth
  -> inspect current state
  -> define one bounded change
  -> implement on a feature branch
  -> focused tests
  -> full validation
  -> review the actual diff
  -> commit
  -> push
  -> pull request
  -> CI
  -> merge
  -> build the complete artifact from the merged commit
  -> verify the artifact
  -> deploy
  -> ha core check
  -> controlled restart
  -> focused live validation
```

Development, publication, deployment, and commissioning are separate authority stages. Do not jump
from local tests to production. Do not deploy unmerged working-tree source as the normal workflow,
and do not commit, push, open a pull request, merge, tag, build, or deploy unless the task authorizes
that stage.

## Validation

Use the repository's configured tools and the strongest checks applicable to the change. The normal
code baseline is:

```bash
python -m compileall poolos intellicenter
python -m ruff check poolos intellicenter tests
python -m mypy poolos
python -m pytest
git diff --check
```

Run focused tests first. Add behavioral regression tests for changed behavior; source-text tests are
only a narrow supplemental guard. Do not weaken tests, silently update golden data, or hide failures
to obtain a green result. Documentation-only work does not require expensive unrelated tests unless
repository tooling or the task requires them.

Equipment-affecting changes additionally require negative tests, closed-loop verification tests,
restart/recovery tests, and fake or injected delivery clients. No repository test may send a real
service call, open an equipment connection, or actuate hardware.

## Diff and Git discipline

Before commit:

- inspect `git status` and the diff stat;
- review the complete actual diff;
- account for every changed production, test, documentation, and generated file;
- confirm no unrelated changes or debug artifacts are included;
- confirm no deployment artifact is included accidentally;
- confirm no authority expansion occurred unless explicitly requested;
- confirm `.local_backups/` remains untouched and uncommitted.

Do not rely on test success alone. Use focused imperative commit messages and avoid mixing features,
refactors, deployment artifacts, and documentation into one commit.

Before merging, review exact diff, commit scope, CI, conflicts, unintended files, and authority
changes. A mergeable status is not approval to merge. Unless explicitly authorized, stop at the
requested publication boundary.

## Packaging and deployment

Build deployment artifacts from the exact intended merged commit, never from arbitrary working-tree
state. Use the repository's packaging and validation tooling. A local Home Assistant commissioning
package must contain the complete intended integration tree and its required vendored PoolOS core,
not a partial file overlay.

Inspect archive contents and reject artifacts containing caches, bytecode, macOS metadata, unrelated
files, or an incorrect nested root. This includes `__pycache__`, `.pyc`, `.DS_Store`, `__MACOSX`, and
AppleDouble `._*` files. Use deterministic ordering when artifact identity matters; use `LC_ALL=C`
for shell sorting that affects hashes or archive contents. Hash the final artifact when provenance
matters.

Before replacing deployed source:

- verify artifact contents and provenance;
- make a timestamped backup of the installed integration;
- install the exact intended complete artifact;
- run `ha core check`;
- do not restart if validation fails;
- restart deliberately only after validation;
- verify integration loading, entities, logs, intended behavior, native parity, and absence of
  unexpected commands;
- retain a tested rollback path through the agreed observation period.

Do not deploy partial files except under an explicitly reviewed emergency procedure.

## Physical commissioning

Passing tests is not commissioning. Progress through shadow observation, advisory output, narrow
commissioning scope, explicit kill switches, controlled live tests, and one behavior at a time.
Never enable broad autonomous authority without observed evidence and explicit approval.

Prefer passive evidence from natural operation when it can answer the question. Avoid unnecessary
equipment activity solely for testing. A commissioning test must define preconditions, exact scope,
expected observations, timeout/failure behavior, rollback, and the point at which work stops.

## Observability and failure behavior

Important decisions should expose bounded structured evidence showing what PoolOS observed, decided,
planned, authorized, delivered, and later confirmed, including rationale, blockers, identity,
provenance, and timing. Observability must remain diagnostic and must not become authority or a
parallel state ledger.

On uncertainty, stop creating new unverified work and preserve the safest known ownership and
equipment assumptions. Turning equipment off is not universally safe, so do not invent an `off`
command as a generic failure response. Observation and advisory planning may remain available while
autonomous execution stays blocked.

Report failures with bounded, sanitized detail. Do not hide meaningful failures merely to keep an
entity available, and do not place full tracebacks or growing evidence collections in Home Assistant
attributes.

## Documentation discipline

Keep enduring rules here; keep implementation detail in source documentation, architecture in the
architecture manual and ADRs, procedures in deployment or commissioning guides, and status in the
roadmap. Do not add current versions, branches, SHAs, pull requests, test counts, deployment hashes,
runtime values, debugging results, or other temporary state to this file.

Use clear imperative language. Update documentation with code that changes contracts, ownership,
safety priority, operating behavior, repository structure, or deployment procedure. The goal is a
constitution that remains useful without routine status maintenance, not a changelog or complete
architecture reference.
