# ADR-111: Coherent observation and accepted-command consequence chronology

## Status

Accepted in PoolOS v1.0.3 after Phase 1 forensic review, repository regression validation, and hosted CI review. Physical commissioning remains a separate evidence level. Complements ADR-110 and clarifies the snapshot-conflict and acceptance-clock rules of ADR-108/ADR-109.

## Context

The October 2 forensic review of v1.0.3 (`99a9122d2f402b9b76bba4abe6ae295181f7181b`)
reproduced five failures. Native callbacks could recompute a new thermal plan
under an earlier coordinator frame; an equal-time changed fingerprint could then
retire ownership established by a later accepted receipt. Filtration dated
acceptance from its authorizing frame and could verify against pre-acceptance
BODY evidence. The native transport refreshed cached unrelated concepts on a
pump callback. Runtime ownership treated an older evaluation as preemption.

The older conflict regression prevented impossible negative lease duration by
clamping retirement to establishment. It preserved the incorrect retirement.
Scenario 88 requires old consequences not to steal newer authority. Fail-closed
command permission must not turn an older fact into authority to cancel newer
positively established provenance.

## Decision

Keep four clocks separate:

- concept observation: when that specific native field was received, or the
  start of the independent read that actually returned it;
- publication: when an immutable captured model is published;
- evaluation: when policy/orchestration is computed from that capture;
- acceptance: the latest authorizing, issued and acknowledged receipt boundary.

`poolos/evidence_chronology.py` supplies temporal admission. It grants neither
ownership nor command permission. Identity, generation, source, quality,
freshness, topology, purpose compatibility and the final gateway remain required.
A command consequence must be **strictly later** than its immutable acceptance
boundary. A matching pre-boundary or equal-boundary value cannot verify it.

Record native chronology per returned field, including genuinely received
unchanged values. Merely remapping a cached model cannot refresh a field. Partial
callbacks leave unrelated clocks unchanged. A delayed read cannot overwrite a
newer field and retain that newer timestamp. Independent reads use their start
boundary, not completion as a fabricated sampling time. Existing generation and
complete-read/intervening-publication fences remain in force. Vendor monitoring
paths that apply replies after `send_cmd()` returns carry the request-start
boundary on that exact returned list; later application cannot renew its age.

Capture the mapped native snapshot and its transport/configuration input inside
the authoritative observation snapshot. Policy, orchestration and execution use
that capture. Fast native publication still updates diagnostics, operator
restraints and command-consequence attribution, and schedules the existing
coordinator refresh; it does not recompute policy under the prior frame.
No new polling loop or sleep is introduced.

Evidence identity identifies captured facts/source/discovery generation;
evaluation identity additionally represents policy and execution intent. Two
independently captured inputs can share a wall-clock timestamp. A policy revision
can evaluate the same facts without claiming new evidence. Exact duplicate
composed frames remain idempotent. Changing relevant facts under the **same
claimed evidence identity** is still a conflict. Legacy callers without an explicit
evidence identity retain the strict equal-time conflict rule.

Admit chronology before ownership mutation or immutable-currentness processing.
An older callback cannot retire newer accepted/confirmed authority. An older BODY
contradiction in a newer publication denies commands and retains provenance;
it does not verify, hand off, or renew a deadline. Trusted current operator intent
is independently admitted for its affected domain even when BODY facts are old.
Current usable topology contradictions and current identity conflicts still fail
closed. No equality-based ownership restoration is added.

Thermal live execution, thermal cleanup, thermal runtime ownership and filtration
share strictly post-acceptance admission. Accepted attempts and verification
bounds use the actual receipt boundary; the DELIVERED lifecycle transition stores
that same boundary. Refresh/duplicate callbacks cannot renew it. An unverified
attempt still faults at its original deadline, without fabricating an External
owner. Typed successor, residual and cleanup generation checks remain unchanged.

## Evidence and limits

The five Phase 1 probes are retained as repository regressions in
`tests/test_observation_command_chronology.py`, with conflict, topology, restart,
operator, strict chronology and fixed-deadline controls. Additional regressions
cover current publication of old BODY facts, delayed metadata overwrite, and
filtration retirement by pre-acquisition facts. The complete existing autonomous
Spa startup/cleanup test injects changed delayed callbacks after accepted commands
for target satisfaction, Solar loss and Pool priority return. Those three variants
fail against unmodified v1.0.3 and pass with this repair.

Native NotifyList telemetry does not prove human origin or expose a device sampling
clock. Its defensible observable boundary is receipt. Read replies provide a
conservative request-start boundary. Neither implies a Pentair latency SLA. Tests
prove software ordering and authority fencing, not physical device performance or
all 90 ownership scenarios. Restart reconstructs no ownership from these captures.

PR #388 must remain unmerged until the complete repair is reviewed. Its isolated
pre-establishment conflict guard is covered here but is not the complete repair.
