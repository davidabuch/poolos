# PoolOS Repository Constitution

## 1. Purpose, scope, and precedence

This file governs engineering work throughout the PoolOS repository.

Treat it as a durable safety, architecture, evidence, and workflow contract for humans and coding agents. More specific task instructions may narrow scope or add constraints, but they must not weaken the safety, authority, provenance, evidence, validation, or deployment rules defined here.

Repository truth and authoritative runtime evidence outrank conversational memory, assumptions, historical notes, filenames, timestamps, or intended behavior.

Before making a material change:

1. inspect the current repository;
2. inspect relevant tests and architecture;
3. identify the actual source of truth;
4. trace the complete affected lifecycle;
5. reproduce the defect or missing contract where practical;
6. define the smallest coherent change;
7. stop rather than improvise if evidence contradicts the requested design.

Do not encode temporary project status in this file.

Branches, SHAs, pull requests, current versions, deployment hashes, test counts, active commissioning observations, and roadmap status belong elsewhere.

---

## 2. Prime directive

Protect people, equipment, and deterministic system behavior before optimizing convenience, automation, performance, or feature completeness.

PoolOS must prefer:

- explicit evidence over inference;
- typed contracts over implicit coupling;
- deterministic state machines over timing guesses;
- fail-closed behavior over optimistic execution;
- bounded changes over speculative refactoring;
- one owner per concept over competing control paths;
- re-observation over assumed command success;
- provenance over state coincidence;
- current truth over stale intent;
- passive evidence over unnecessary equipment activity.

Passing tests alone does not make a change safe.

Always review the actual production diff.

---

## 3. Canonical closed-loop model

Equipment-affecting PoolOS behavior follows:

```text
observe
  -> evaluate
  -> decide
  -> plan
  -> authorize
  -> execute
  -> deliver
  -> re-observe
  -> verify
  -> continue / hand off / relinquish / fail closed
```

These are separate stages.

No stage may silently grant authority belonging to another stage.

In particular:

- observation does not authorize;
- policy recommendation does not authorize;
- a valid plan does not authorize;
- adapter availability does not authorize;
- entity availability does not authorize;
- delivery does not prove physical success;
- matching observed state does not prove PoolOS caused it;
- verification of matching state does not manufacture ownership;
- a completed execution does not automatically authorize its successor.

Do not issue a dependent operation until authoritative evidence confirms the prerequisite operation when the plan requires ordered verification.

---

## 4. State, intent, observation, and provenance

Keep these concepts distinct in models, diagnostics, tests, and documentation:

- user-requested state;
- policy recommendation;
- desired state;
- planned state;
- native configured state;
- command requested by PoolOS;
- command authorized by PoolOS;
- command submitted by PoolOS;
- command accepted by the delivery boundary;
- observed actual equipment state;
- verified post-command state;
- execution provenance;
- runtime ownership.

Never collapse these concepts merely because their current values happen to agree.

For pumps, separately represent:

- requested/planned RPM;
- native configured RPM or preset;
- commanded RPM;
- observed actual RPM.

A configured pump preset is not proof that the pump is running.

An observed RPM matching a PoolOS target is not proof that PoolOS caused it.

The same rule applies to body activity, heat source, valves, circuits, and other equipment state.

---

## 5. Unknown, stale, degraded, and contradictory evidence

Unknown evidence is a first-class state.

Do not translate unknown evidence into:

- `0`;
- `False`;
- `off`;
- an empty string;
- a default equipment state;
- a successful verification.

Autonomous execution must fail closed when required evidence is:

- missing;
- stale;
- unusable;
- contradictory;
- temporally regressive;
- below required confidence;
- insufficiently correlated;
- otherwise unsafe for the requested decision.

Diagnostic or advisory behavior may remain available when execution is blocked.

Do not weaken freshness, quality, chronology, or confidence requirements merely to make a plan executable.

---

## 6. Architecture and dependency direction

Dependencies point toward more foundational abstractions:

```text
canonical domain
  -> observations and environment
  -> policy and decision
  -> planning
  -> authorization
  -> supervisory/runtime ownership
  -> execution
  -> delivery adapters
  -> physical transport
```

Runtime flow may proceed toward physical delivery, but platform and vendor details must not leak backward into core policy.

### Core PoolOS

Core PoolOS owns vendor-neutral:

- canonical domain models;
- observations;
- policy;
- decisions;
- planning;
- authorization contracts;
- ownership contracts;
- execution contracts;
- verification semantics;
- reason codes.

### Coordinators

Coordinators own:

- connection lifecycle;
- authoritative live-model coordination;
- event-driven publication;
- bounded refresh orchestration.

Coordinators must not become parallel policy engines or hidden equipment controllers.

### Immutable read boundaries

Read APIs normalize mutable external models into immutable evidence.

They must not:

- decide policy;
- grant ownership;
- grant physical authority;
- issue commands.

### Home Assistant entities

Entities adapt published state for:

- presentation;
- diagnostics;
- explicit user requests.

They must not become a second autonomous control engine.

### Delivery adapters

Delivery adapters translate an already-authorized canonical operation and return evidence.

They must not invent:

- goals;
- policy;
- ownership;
- authority;
- additional operations;
- recovery commands;
- unrelated state changes.

### Physical transport

Vendor-specific physical transport remains behind narrow adapters and explicit allowlists.

Command capability is not permission to use it.

---

## 7. Authority is explicit and monotonic toward safety

Shadow, advisory, planning, diagnostics, and simulation must not silently become live authority.

Authority increases require:

- explicit scope;
- explicit policy;
- explicit authorization;
- review;
- negative tests;
- commissioning evidence;
- operator approval where required.

Failures may automatically reduce authority.

Failures must not automatically increase authority.

Preserve:

- kill switches;
- commissioning scopes;
- maintenance gates;
- controller-mode gates;
- freshness requirements;
- ownership requirements;
- operation allowlists;
- equipment allowlists;
- verification deadlines;
- recovery boundaries.

Do not bypass a blocker merely because the requested operation appears reasonable.

---

## 8. Ownership model

Ownership is a safety concept, not a synonym for matching state.

PoolOS distinguishes at least three concepts:

```text
session execution ownership
runtime lifecycle ownership
observed equipment state
```

They must remain separate.

### 8.1 Session execution ownership

Session execution ownership proves what one exact execution session actually delivered.

It may originate only from positive PoolOS execution provenance such as:

- exact operation identity;
- accepted delivery receipt;
- execution/session correlation identity;
- accepted body activation;
- accepted pump setpoint;
- accepted heat-source command.

Authorization alone is not ownership.

Planning alone is not ownership.

Observed state alone is not ownership.

### 8.2 Runtime lifecycle ownership

Runtime ownership represents whether PoolOS remains entitled to continue controlling equipment or concepts that PoolOS genuinely caused across compatible execution or plan boundaries.

Runtime ownership must originate from accepted PoolOS provenance or an explicit valid ownership handoff.

It must never originate from state coincidence.

### 8.3 Observed state cannot manufacture ownership

These observations alone never establish ownership:

```text
pool.active == true
spa.active == false
pump.rpm == expected_rpm
heat_source == expected_source
```

They may confirm, contradict, or revoke existing ownership.

They cannot create it.

This applies even when the observed equipment state exactly matches a PoolOS plan.

---

## 9. Concept-specific ownership

Do not claim more ownership than PoolOS actually established.

Where practical, preserve separate provenance for concepts such as:

- body activation;
- pump setpoint;
- heat source;
- other explicitly controlled equipment concepts.

A session that only delivered a pump setpoint must not claim body activation ownership.

A session that only selected a heat source must not manufacture pump ownership.

Aggregate lifecycle ownership may be useful for supervisory decisions, but the underlying provenance must remain exact.

---

## 10. Ownership handoff

Ownership must not automatically flow from one plan, evaluation, or execution session to another.

A handoff must be explicit and typed.

A valid handoff must require appropriate evidence such as:

- valid predecessor ownership;
- valid predecessor provenance;
- current successor evaluation;
- current successor plan;
- compatible body;
- compatible owned concepts;
- fresh usable hydraulic evidence;
- no preemption;
- explicit caller intent to perform the handoff.

Matching observed state is not a handoff.

Matching requested state is not a handoff.

Matching RPM is not a handoff.

A new plan for the same body is not automatically a handoff.

Cross-body ownership transfer must not occur unless a separately reviewed architecture explicitly permits it.

---

## 11. Ownership preemption

Manual or external intervention affecting an owned concept must fail closed.

Relevant events may include:

- owned body unexpectedly becoming inactive;
- other body becoming active;
- contradictory simultaneous body activity;
- externally changed pump RPM;
- externally changed heat source;
- conflicting hydraulic routing;
- stale or unusable hydraulic evidence;
- incompatible newer evaluation or plan;
- maintenance or controller authority changes;
- confirmed safety events supported by canonical evidence.

Preemption must revoke the affected authority rather than silently reconciling ownership from the new observed state.

A preempted ownership state must not silently become owned again.

Fresh provenance or an explicit valid handoff is required.

---

## 12. Expected consequences and external changes

PoolOS must distinguish its own expected command consequences from unrelated external changes.

Reuse one canonical attribution/correlation mechanism where one exists.

Do not create competing command-attribution systems.

An expected, correlated consequence of an accepted PoolOS command must not cause PoolOS to preempt itself.

Attribution must be concept-specific.

For example:

```text
PoolOS expects pump.rpm -> 2900
```

If an observation contains:

```text
pump.rpm -> 2900        # expected PoolOS consequence
heat_source -> Gas      # unrelated external change
```

the expected pump consequence may remain attributed to PoolOS, but the unrelated heat-source change must still be evaluated independently for preemption.

Do not suppress an entire observation merely because one field matches an expected consequence.

---

## 13. Relinquishment is not a command

Relinquishing ownership means PoolOS no longer claims authority over the concept.

It does not automatically mean:

- stop the pump;
- turn a body off;
- restore a prior RPM;
- restore a prior source;
- restore a prior valve state;
- issue any compensating command.

Physical cleanup requires its own:

- ownership;
- policy;
- authorization;
- current safety evidence;
- verification contract.

Turning equipment off is not universally the safest failure response.

Do not invent OFF, STOP, or restoration commands as generic cleanup.

---

## 14. Session currentness and supersession

An execution session is bound to immutable originating identity.

Where evaluations and plans have explicit identities, physical execution must remain bound to the correct current identity.

Currentness must be checked:

- before physical delivery;
- before verification;
- before advancement to dependent operations.

If the originating evaluation or plan has been superseded:

- do not deliver another operation;
- do not verify stale work as permission to continue;
- do not advance the stale execution;
- discard any incomplete verification hold that depends on the superseded session;
- require a fresh current execution decision.

A stale session must not resume merely because equipment later matches its old target.

---

## 15. Restart and reload semantics

Restart and reload are authority boundaries.

Do not reconstruct active execution or runtime ownership merely because post-restart equipment state matches previous PoolOS commands.

Unless a separately reviewed persistence contract explicitly proves safe ownership restoration:

```text
new runtime -> unowned
```

Equipment already running after restart must be treated as pre-existing/external for ownership purposes until fresh PoolOS provenance establishes otherwise.

Do not blindly replay incomplete operations after restart.

Do not infer interrupted command completion from matching state alone.

Restored diagnostic state must not actuate equipment.

---

## 16. Thermal and hydraulic safety

Treat all equipment-affecting thermal behavior as safety-sensitive.

Keep separate:

- body activity;
- body configuration;
- hydraulic route;
- valve position;
- pump operation;
- pump speed;
- configured heat source;
- effective heat source;
- actual heating state.

Do not assume one from another.

A configured body is not proof that the body is active.

A selected heat source is not proof that heat is flowing.

A requested pump speed is not proof that the pump reached that speed.

Hydraulic continuity required by an execution step must remain continuously proven for the duration required by that step.

Contradictory body topology must fail closed.

Shared hydraulic circuits must be evaluated according to proven routing semantics rather than assumed safe or unsafe by name.

When repository evidence cannot prove a potentially conflicting hydraulic state safe, fail closed.

---

## 17. Priming and timed verification

Timed physical requirements must be modeled as deterministic state and evidence, not sleeps.

For any operation requiring a verified hold:

- establish the required state;
- re-observe authoritative evidence;
- verify continuity throughout the required interval;
- invalidate the hold if required continuity is lost;
- do not retain partial credit across a known interruption unless policy explicitly permits it.

Do not use `sleep()` as proof that equipment remained in the required state.

---

## 18. Solar and heat-source principles

Keep distinct:

- collector availability;
- water-temperature evidence;
- Solar eligibility;
- requested policy mode;
- planned source;
- native selected source;
- actual heating state.

Favorable collector temperature alone does not authorize Solar.

Rapid heat-up preference alone does not authorize Gas.

Respect:

- user intent;
- target demand;
- source eligibility;
- body state;
- hydraulic safety;
- ownership;
- freshness;
- hysteresis;
- activation/deactivation rules;
- source-specific authorization.

Prefer deterministic state machines over sleeps, polling workarounds, or timing guesses.

Do not hide source chatter by weakening thresholds, freshness, or evidence.

---

## 19. Temperature acquisition and probe principles

Temperature acquisition is evidence gathering, not heat-source authority.

A temperature probe lifecycle must preserve:

- explicit acquisition ownership;
- hydraulic continuity;
- chronological samples;
- bounded history;
- minimum acquisition requirements;
- stability requirements;
- maximum acquisition duration;
- clear success/failure state.

Probe circulation must not be mistaken for ordinary pre-existing circulation.

Samples from different known hydraulic epochs must not be combined.

A failed or interrupted acquisition must not manufacture trusted temperature evidence.

Probe RPM coincidence alone must never establish probe ownership.

Any future physical probe authority requires explicit commissioning and authorization independent from the command-free probe decision model.

---

## 20. Filtration principles

Filtration is an obligation, not merely a schedule.

Deferral must not erase outstanding work.

A scheduled interval is not proof that circulation occurred.

Credit filtration only from authoritative observed circulation satisfying the filtration policy.

Do not credit Spa-only circulation as Pool filtration unless policy explicitly allows it.

Preserve existing:

- temperature bands;
- time-of-use policy;
- debt semantics;
- operational-day semantics;
- ledger ownership;
- RPM credit bands;

unless the task explicitly changes them.

Thermal ownership does not automatically imply filtration ownership.

Filtration ownership does not automatically imply thermal ownership.

Any future ownership handoff between these systems must be explicit.

Do not create a second filtration ledger.

---

## 21. Outage and safety-event architecture

Use one canonical safety-event model per concept.

Do not create duplicate outage detectors or competing outage state machines.

Raw grid state is not automatically equivalent to a confirmed outage.

If a subsystem requires confirmed outage evidence, consume the canonical confirmed state rather than independently implementing:

- another timer;
- another debounce;
- another poller;
- another helper;
- another confirmation rule.

If canonical evidence is insufficient, report the missing prerequisite instead of inventing a parallel architecture.

---

## 22. Native IntelliCenter parity

Native IntelliCenter behavior is a major regression boundary.

Before changing:

- entity semantics;
- units;
- availability;
- climate behavior;
- body behavior;
- pump behavior;
- heat-source behavior;
- circuit interpretation;
- subscriptions;
- state normalization;

inspect the corresponding native behavior and the complete acquisition-to-publication path.

Do not normalize away meaningful distinctions among:

- native configured state;
- PoolOS desired state;
- PoolOS plan;
- requested state;
- actual observation.

If PoolOS intentionally diverges from native behavior, document the reason and cover it with behavioral tests.

Do not expose a general-purpose mutable IntelliCenter controller through a read boundary.

Read/query capability is not command authority.

Command capability is not permission to use it.

---

## 23. Home Assistant and event-loop rules

Avoid:

- blocking the Home Assistant event loop;
- recursive refresh loops;
- self-triggering state loops;
- uncontrolled background tasks;
- unbounded task creation;
- competing refresh owners;
- competing state sources;
- heavy disk work on frequent coordinator paths;
- heavy network work on frequent coordinator paths;
- storage churn;
- unbounded write frequency;
- polling where reliable event-driven state exists;
- growing Recorder attributes;
- large diagnostic state payloads.

Be explicit about:

- coordinator refresh ownership;
- subscription ownership;
- task cancellation;
- unload behavior;
- restart behavior.

Native publication must not be delayed by unrelated durable work when separate publication and persistence boundaries exist.

Diagnostics must not mutate execution state.

---

## 24. Temporal evidence and persistence

Stateful trackers must preserve chronological evidence.

Do not weaken timestamp invariants to silence temporal regression errors.

When multiple authoritative snapshots exist, do not regress a tracker to older evidence.

Repeated evaluation of the same observation must not double-count work.

Refreshes must not invent completed work.

Stale evidence must not satisfy an obligation.

Persistent state must explicitly address:

- restart;
- reload;
- schema compatibility;
- duplicate observations;
- out-of-order observations;
- retention;
- bounded growth;
- day rollover where relevant;
- debt carry-forward where relevant;
- ownership of the persisted ledger.

Persist only deterministic, versioned, bounded, privacy-safe evidence where persistence is actually required.

Reject malformed or incompatible persisted state fail closed without breaking authoritative observation processing.

Do not create overlapping stores for the same source of truth.

---

## 25. Observability

Important decisions should expose bounded structured evidence showing what PoolOS:

- observed;
- evaluated;
- decided;
- planned;
- authorized;
- delivered;
- verified;
- owns;
- relinquished;
- rejected;
- blocked.

Include useful:

- identity;
- provenance;
- timestamps;
- reason codes;
- blockers;
- disposition.

Observability is diagnostic.

It must not become:

- authority;
- a parallel state ledger;
- a command trigger;
- an ownership source.

Keep detailed history in its owned evidence store rather than high-frequency Home Assistant attributes.

Do not expose:

- credentials;
- tokens;
- raw network addresses where unnecessary;
- traceback-sized errors;
- unbounded protocol payloads;
- growing evidence collections.

---

## 26. Inspection before implementation

Before editing production code, inspect the complete affected lifecycle.

As applicable, inspect:

- implementation;
- callers;
- behavioral tests;
- regression tests;
- canonical models;
- state ownership;
- timestamp ownership;
- persistence ownership;
- retention;
- coordinator flow;
- event-loop behavior;
- entity exposure;
- Recorder impact;
- policy;
- planning;
- authorization;
- ownership;
- execution;
- delivery;
- verification;
- external-change attribution;
- restart;
- unload;
- failure;
- recovery;
- native parity.

Trace actual data flow.

Do not infer behavior merely from class names or function names.

For a live defect, identify the earliest boundary where evidence becomes wrong, stale, contradictory, or stops moving.

Where practical, reproduce the defect with an executable test before modifying production behavior.

---

## 27. Change scope

Make one coherent, reviewable change on a fresh feature branch based on current remote truth.

Do not reuse an old merged branch for unrelated work.

Preserve unrelated user changes.

Stop if unrelated changes overlap the task.

Do not opportunistically:

- refactor unrelated code;
- redesign unrelated architecture;
- broaden execution while fixing planning;
- broaden authority while fixing diagnostics;
- add physical commands while implementing command-free policy;
- combine deployment artifacts with source changes.

A bounded change may cross several files or layers when required to complete one coherent contract.

"Smallest coherent change" does not mean leaving a known safety contract half-implemented merely to minimize line count.

If correctness requires a materially different architecture or authority grant outside the agreed task, stop and report that boundary.

---

## 28. Editing practice

Use structured, reviewable patches.

Do not make giant exact-string Python `.replace()` scripts the normal editing method.

Do not depend on brittle large-block source matching.

Prefer portable commands that work on macOS.

Do not assume GNU-only flags.

When providing interactive commands, label them:

```text
MAC TERMINAL
```

or:

```text
HOME ASSISTANT TERMINAL
```

Do not assume `/config` exists on macOS.

Do not assume the local Git repository exists in the Home Assistant terminal.

Do not default interactive user instructions to `set -eu`.

Use readable validation and explicit STOP conditions.

---

## 29. Source truth, GitHub truth, artifact truth, and deployed truth

These are separate:

```text
repository source
GitHub branch/PR state
merged commit
release/tag
deployment artifact
installed Home Assistant source
runtime behavior
```

Do not infer one from another.

A matching version number does not prove matching source.

A newer filesystem timestamp does not prove newer code.

The repository is the development source of truth.

Home Assistant is a deployment target, not the primary editing environment.

When provenance matters, verify:

- exact commit;
- exact merge;
- exact tag/release where applicable;
- exact artifact;
- exact installed source.

---

## 30. Development workflow

Unless a task explicitly stops at an earlier stage, use:

```text
repository truth
  -> inspect current state
  -> define bounded change
  -> fresh feature branch
  -> reproduce defect / missing contract
  -> implement
  -> focused tests
  -> expanded relevant tests
  -> full validation
  -> review complete actual diff
  -> commit
  -> push
  -> pull request
  -> CI
  -> human review
  -> merge
  -> synchronize merged main
  -> decide whether a release is warranted
  -> build artifact from exact merged/released commit
  -> verify artifact
  -> deploy
  -> ha core check
  -> deliberate restart
  -> focused live validation
  -> bounded observation
  -> broader commissioning only after evidence
```

Development, publication, release, deployment, and commissioning are separate authority stages.

Do not jump from local tests to production.

Do not deploy unmerged working-tree source as the normal workflow.

Do not commit, push, open a PR, merge, tag, release, package, or deploy unless the current task authorizes that stage.

A merge does not automatically imply a release.

A release does not automatically imply deployment.

Deployment does not automatically imply enabling live authority.

---

## 31. Validation baseline

Use the repository's configured tools and the strongest applicable checks.

Run focused tests first.

For normal Python production changes, the baseline full validation is:

```bash
python -m pytest
python -m ruff check .
python -m mypy poolos
python -m compileall poolos custom_components/poolos intellicenter tests
git diff --check
```

If repository configuration changes these commands, use current repository truth.

Add behavioral regression tests for changed behavior.

Source-text tests are supplemental guards, not substitutes for behavior tests.

Do not:

- weaken tests to make a change pass;
- silently rewrite expected/golden data;
- hide warnings or failures;
- skip relevant tests without reporting it.

Documentation-only work does not require expensive unrelated tests unless repository tooling or the task requires them.

Equipment-affecting changes additionally require:

- negative authorization tests;
- closed-loop verification tests;
- stale/missing evidence tests;
- ownership tests;
- supersession tests;
- restart/recovery tests;
- injected fake delivery clients.

Repository tests must never contact live Home Assistant, IntelliCenter, networks, or physical equipment.

---

## 32. Diff and Git discipline

Before commit:

1. inspect `git status`;
2. inspect `git diff --stat`;
3. review the complete actual diff;
4. account for every changed file;
5. inspect production changes independently from tests;
6. confirm no debug artifacts;
7. confirm no accidental deployment artifacts;
8. confirm no unintended authority expansion;
9. confirm unrelated user files remain untouched;
10. confirm `.local_backups/` remains untouched and uncommitted.

Passing tests does not replace diff review.

Use focused imperative commit messages.

Do not mix unrelated:

- features;
- refactors;
- deployment artifacts;
- generated files;
- documentation changes unrelated to the implementation.

Before merge, review:

- exact diff;
- commit scope;
- CI;
- conflicts;
- unintended files;
- authority changes.

Mergeability is not approval to merge.

---

## 33. `.local_backups/`

`.local_backups/` is intentionally local and untracked.

Unless a task explicitly concerns that directory:

- do not modify it;
- do not delete it;
- do not stage it;
- do not commit it;
- do not package it;
- do not treat its presence as a dirty-tree failure.

Safety checks should distinguish `.local_backups/` from unexpected working-tree changes.

---

## 34. Packaging and release

Build deployment artifacts only from the exact intended merged or released commit.

Never build a production deployment artifact from arbitrary uncommitted working-tree state.

Use repository packaging and validation tooling.

A Home Assistant commissioning package must contain the complete intended integration tree and required vendored PoolOS core, not an accidental partial overlay.

Inspect archives and reject:

- `__pycache__`;
- `.pyc`;
- `.DS_Store`;
- `__MACOSX`;
- AppleDouble `._*`;
- unrelated source;
- incorrect nested roots;
- local backups;
- development-only artifacts.

Use deterministic ordering when artifact identity matters.

Use `LC_ALL=C` for shell sorting when ordering affects hashes or archives.

Hash final artifacts when provenance matters.

---

## 35. Deployment

Before replacing installed Home Assistant source:

1. verify exact artifact provenance;
2. verify archive contents;
3. create a timestamped backup of the installed integration;
4. install the complete intended artifact;
5. run `ha core check`;
6. stop if validation fails;
7. restart deliberately only after validation;
8. verify integration loading;
9. verify entities and diagnostics;
10. inspect logs;
11. verify intended behavior;
12. verify native parity where applicable;
13. verify absence of unexpected commands;
14. retain rollback through the agreed observation period.

Do not deploy partial files except under an explicitly reviewed emergency procedure.

---

## 36. Physical commissioning

Passing tests is not commissioning.

Commission progressively:

```text
simulation
  -> shadow observation
  -> advisory output
  -> command-free readiness
  -> narrow commissioning scope
  -> explicit kill switch
  -> one controlled live behavior
  -> re-observation and verification
  -> bounded observation period
  -> broader authority only after evidence
```

Never enable broad autonomous authority merely because code merged successfully.

Prefer passive evidence from natural operation when it can answer the question.

Avoid unnecessary equipment activity solely for testing.

Every live commissioning test must define:

- prerequisites;
- exact scope;
- exact expected operations;
- expected observations;
- verification requirements;
- timeout/failure behavior;
- preemption behavior;
- rollback/recovery boundary;
- explicit stopping point.

---

## 37. Failure and recovery

On uncertainty:

- stop creating new unverified work;
- preserve authoritative observations;
- revoke unsafe authority;
- retain useful diagnostics;
- require fresh evaluation before continuation.

Do not assume stopping equipment is always safest.

Do not invent compensating commands.

Recovery commands require explicit reviewed policy and authority.

A failed execution must not silently replay merely because conditions later appear favorable.

A superseded execution must not resume.

A preempted ownership state must not silently reacquire authority.

---

## 38. Documentation discipline

Keep durable engineering rules in this constitution.

Use:

- source documentation for implementation contracts;
- ADRs for cross-layer or difficult-to-reverse architecture;
- architecture manuals for system structure;
- deployment guides for deployment procedure;
- commissioning guides for live testing procedure;
- roadmaps for status and sequencing;
- release notes for shipped changes.

Do not put temporary project state here.

Do not add:

- current branches;
- current SHAs;
- current PR numbers;
- current test counts;
- deployment hashes;
- temporary runtime values;
- debugging results;
- short-lived implementation sequencing.

Update enduring documentation whenever code materially changes:

- authority;
- ownership;
- handoff;
- preemption;
- safety priority;
- persistence;
- execution semantics;
- operating behavior;
- deployment procedure;
- architectural boundaries.

---

## 39. Coding-agent conduct

Coding agents must inspect before assuming.

A coding agent must not:

- infer repository state from conversation alone;
- treat historical documentation as newer than current code without evidence;
- broaden scope merely because adjacent work appears useful;
- grant authority to make tests pass;
- contact live Home Assistant or equipment during repository tests;
- stage, commit, push, merge, release, package, or deploy unless explicitly authorized;
- hide a STOP condition;
- manufacture certainty from incomplete evidence.

When a task requests implementation but a safety prerequisite is missing:

1. identify the exact missing prerequisite;
2. determine whether it can be solved within the bounded task;
3. implement it only if doing so remains coherent and within authority;
4. otherwise stop and report the blocker precisely.

Do not stop merely because a future feature is incomplete if the requested bounded foundation can be safely completed independently.

---

## 40. Final review questions

Before declaring an engineering task complete, answer internally:

### Evidence
- What is the authoritative evidence?
- Is it current?
- Is it chronological?
- Are unknowns preserved?

### Policy
- Did policy remain separate from observation and delivery?
- Did any diagnostic path become authority?

### Ownership
- What does PoolOS actually own?
- What provenance establishes that ownership?
- Could matching observed state accidentally manufacture ownership?
- Can manual/external intervention preempt it?
- Can ownership cross a boundary only through explicit handoff?

### Execution
- Is the plan current?
- Is authorization current?
- Is the execution session current?
- Is verification bound to the same current identity?
- Can a stale or superseded execution continue?

### Physical safety
- Were any allowlists broadened?
- Were any blockers weakened?
- Were new commands introduced?
- Is every dependent command verified before continuation?

### Restart
- Could restart reconstruct authority incorrectly?
- Could restored state replay equipment commands?
- Does restart fail closed where ownership is uncertain?

### Home Assistant
- Is the event loop protected?
- Is there one refresh/state owner?
- Are diagnostics bounded?
- Could entity publication create a feedback loop?

### Validation
- Were focused tests run?
- Were relevant expanded tests run?
- Did the full suite pass?
- Did Ruff pass?
- Did MyPy pass?
- Did compileall pass?
- Did `git diff --check` pass?
- Was the complete diff reviewed?

### Git and deployment
- Are all changed files intentional?
- Is `.local_backups/` untouched?
- Is source provenance exact?
- Has the task stopped at the authority stage actually requested?

If any answer is uncertain for a safety-critical path, do not declare the work complete.
