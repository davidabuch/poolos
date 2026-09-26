# Reset and domain hand-back recovery — September 26, 2026

Baseline: recovery `ddfd7d444036e60e51b9a146134084efb4aacc40`
(v0.11.69). Candidate branch: `fix/recovery-reset-domain-handback`.
This is software evidence, not physical commissioning.

## Reset: completion responsibility outlived the service task

The button opens the shared physical-authority Reset generation, synchronously
invalidates sessions, sends source/body reductions, and awaits bounded
verification. v0.11.69 only closed Reset inside that coroutine. Exhausting both
verification windows, or cancellation of the awaited final refresh, left the
fence active with no observation-driven continuation. Subsequent authoritative
OFF/0 could not complete that generation. Restart constructed a new authority
object and removed the in-memory fence, explaining the reported recovery.

The regression exercises the real button with injected HA boundary objects,
including actual `Task.cancel()`, cancellation during reduction/final refresh,
delivery exception, and exhausted verification. It proves that later safe
evidence was ignored on the baseline. It does not prove which exit happened in
the physical run: the original service traceback was not supplied. Inspection
of upstream HA's blocking service invocation does not establish a universal
service cancellation deadline. No timeout constant was increased.

Construction in `custom_components/poolos/__init__.py` passes the same physical
authority from pump composition to manual, thermal, filtration, external-change,
and config-entry runtime consumers. The button reads that runtime reference;
ordinary refresh does not recreate it. The only production Reset opener is the
button. There is no demonstrated finish-on-object-A/read-object-B or reopen path.
Older unconditional-finally closure could clear the fence without verifying
physical safety; it is deliberately not restored.

The button now registers an entry-lifetime, command-free completion listener.
After session invalidation and service exit, it may close only its exact active
Reset generation. Required evidence is native LIVE/GOOD, no older than 30 seconds,
strictly after the most recent reduction submission, and nonfuture: Pool OFF,
Spa OFF, both selected sources OFF, Solar inactive, Gas inactive, and actual RPM
0. Missing source evidence is not OFF. No listener retries physical commands.
The shared authority exposes `reducing`, `waiting_for_fresh_evidence`,
`session_invalidation_failed`, and `complete`. Failed session invalidation cannot
be cleared by matching equipment state. Entry unload removes the listener; a new
button/runtime does not infer the old Reset token from hardware equality.

## PUMP: intent preceded a different execution purpose

A configured-speed hand-back can produce actual 0/high RPM before convergence.
The existing domain episode retained valid adopted PUMP provenance, but the
driver could construct an unissued cold-start priming plan and then lose that
origin through purpose supersession. It now waits on that existing fixed episode
when no command is in flight, retiring only an unissued/completed plan. Termination
and circulation cleanup are processed first. The deadline/budget is not renewed;
exhaustion stays an observable domain fault. New positive operator intent still
wins PUMP alone. Actual RPM equality remains insufficient for hand-back.

## THERMAL: replay and typed successor inconsistencies

HXSLR delegates policy; it does not prove H0002 or Solar activity. Its consumed
operator event was not retained independently of source command provenance, so
replay could assign Operator again after the policy hand-back. Domain state now
retains the consumed evidence separately, scoped to domain, authority generation,
body session and chronology. Newer operator intent is not suppressed. Both event
entry points use the same consumed-event rule.

The production native boundary consumes configured THERMAL intent before policy
evaluation, as it already did for PUMP. The HXSLR source-neutralization plan now
declares its existing ordinary-circulation operating purpose. The driver reuses
the orchestrator's compatible BODY successor predicate for adopted user Spa
purposes; handoff replacement checks include adoption origins, not only command
receipts. The typed handoff still checks body/currentness/hydraulics. No cross-body
transfer or HXSLR-to-H0002 alias was added.

After policy hand-back leaves THERMAL at None, a genuinely new accepted source
command can promote that domain to PoolOS. Acceptance must be explicitly
timestamped strictly after hand-back and no later than promotion. A delayed old
receipt or missing acceptance timestamp cannot acquire authority. This additional
negative regression caught and corrected an overly broad first implementation.

## Deterministic evidence and limits

- `tests/test_reset_recovery_lifecycle.py`: late safe evidence after five exit
  paths, stale/missing/old-boundary/bad-quality/simulated negatives, pump900
  rejection, unload/new-button isolation; owned Pool Solar through Reset and a
  new autonomous Pool Solar generation without restart.
- `tests/test_domain_handback_lifecycle.py`: continuous adopted Spa BODY;
  configured3200 takeover through actual0/3450/3200; actual2900 alone not hand-back;
  configured2900 return through actual0/3450/2900; finite timeout/new operator;
  Gas takeover; direct Solar and HXSLR policy return, including delayed physical
  Solar engagement. No BODY cycling or autonomous Gas command is allowed.
- `tests/test_thermal_runtime_ownership.py`: HXSLR replay and post-hand-back
  accepted-receipt chronology. Existing domain isolation, generation, no-equality
  adoption, topology, and takeover tests remain in place.
- The source-string Reset guard was updated to check the continuation location;
  behavioral tests, not that string guard, establish recovery.

Tests use the production evaluator/orchestrator/driver and button with fake
delivery/native snapshots. They do not run a real HA service registry or predict
firmware response timing. The configured user-Spa preparation RPM policy is
unchanged. Selected source and physical engagement are modeled separately.

An isolated tracked-file export of v0.11.69 with the new lifecycle tests reproduces
the failures without modifying the candidate: late safe Reset evidence leaves
`reset_recovery_active` true; configured PUMP hand-back with actual0 leaves PUMP
Operator rather than PoolOS. The intermediate HXSLR regression exposed
`hot_tub_operating_purpose_rpm_mismatch` and adoption replacement exposed
`runtime_ownership_handoff_denied:pump_incompatible` before their corrections.

Local validation on the candidate: 475 focused tests passed; full pytest 3564
passed with the existing deliberate duplicate-ZIP warning; Ruff, MyPy (217 core
files), compileall, and whitespace validation passed. Hosted Quality, Hassfest,
and HACS must be checked on the published PR head before merge; green local tests
do not stand in for physical acceptance.

## Physical acceptance after independent review and release

1. Healthy owned Pool Solar/2900: press Reset once. Observe old generation retire,
   source/body OFF and actual0, Reset complete, then fresh Pool generation/probe/
   preparation/Solar/2900 without HA restart or manual re-enable.
2. Stable user Spa Solar: configured2900 to3200 yields PUMP only; native0/high RPM
   must not change BODY/THERMAL. Return configured speed to exact desired2900;
   observe one bounded episode and verified convergence.
3. Select Gas explicitly: THERMAL only yields, PUMP follows the existing Gas
   requirement and BODY remains the same user session. Return direct Solar, then
   separately exercise HXSLR with qualified and unqualified roof conditions.
   Verify policy/source/physical activity separately and no BODY cycling.

At the first failed checkpoint, preserve native/authority/generation/episode
evidence, stop commissioning, and have the operator restore useful Pool Solar
operation. Do not repeatedly patch or reset live equipment. No release,
deployment, equipment access, or physical acceptance was performed in this pass.
