# PoolOS ownership semantics

## Status and authority

Accepted behavioral specification. Stage 1 froze semantics; the reviewed Stage 2
implementation subset is recorded in
[STAGE_2_LIFECYCLE_RECONCILIATION.md](STAGE_2_LIFECYCLE_RECONCILIATION.md). This document and
[ADR-110](../adr/ADR-110-ownership-contract-semantics.md) incorporate the complete
[accepted 90-scenario contract](PoolOS_Ownership_Scenario_Contract.txt) into
repository governance. Every scenario is normative. The imported text is preserved
byte-for-byte; its original precedence paragraph describes its pre-incorporation
status. AGENTS.md now incorporates it explicitly. This specification resolves
older ownership terminology without overriding the constitution's physical safety,
authorization, currentness, or commissioning gates.

The [traceability matrix](scenario_traceability.json) records implementation gaps,
not a second source of desired outcomes. Code and tests remain evidence only for
their mapped scenarios, not blanket conformance. Stage 2 activates fixed in-memory
reconciliation episodes with a 120-second deadline and two correction identities;
it does not authorize new persistence, Reset, general adoption, or command
envelopes outside the mapped implementation.

## 1. Four independent axes

Each BODY, PUMP, and THERMAL domain has four separately inspectable axes:

| Axis | Vocabulary | Meaning |
| --- | --- | --- |
| Historical provenance/origin | accepted PoolOS command; typed transfer; prospective adoption; explicit operator request; unknown | Immutable evidence of how responsibility originated, with exact identity and time. |
| Current authority | PoolOS; External/operator; Safety; None/Unowned | Who currently governs this domain and its defined scope. Unknown origin maps to None/Unowned, not an invented operator. |
| Execution/convergence health | pending; converging; stable; degraded/reconciling; faulted | Whether consequences are verified and current control is effective. A fault is not an owner. |
| Current command permission | allowed or denied, with exact operation and reason | A fresh authorization for a concrete operation, epoch, generation, target and value; never implied by an owner label. |

BODY means the physical body's session and completion responsibility. PUMP means
the current speed requirement and its convergence. THERMAL means source governance,
including an intentional Off requirement; it does not mean heat is flowing.
Ownership of one domain does not create accepted receipts or authority in another.
An accepted command is historical origin, not proof of its consequence. A pending
body acceptance cannot supply verified pump or body-cleanup evidence.

For example, a valid PoolOS body origin may survive a temporary evidence outage
with PoolOS lifecycle responsibility retained, health awaiting evidence, and all
body commands denied. Historical origin remains inspectable after terminal
disposal too, but is not usable as a live entitlement. A completed, verified OFF
session ends as INACTIVE/UNOWNED, not External; future independent policy remains
eligible to acquire a new session.

## 2. Evidence classification and operator intent

Use one canonical classification consumed by ownership, execution, pump sessions,
termination, circulation arbitration, safety and HA diagnostics. Do not duplicate
different meanings of an unmatched event in each consumer.

| Evidence class | Required distinction and response |
| --- | --- |
| Expected native transition/convergence | Current causal command or reviewed transition envelope explains it; retain origin, verify within fixed bounds. |
| Unexplained drift | Fresh telemetry differs but origin is unproven; retain valid origin, deny unsafe steps, reconcile boundedly. |
| Positive operator intervention | An explicit attributable request identifies domain, intent and scope; yield only affected domains, subject to safety. |
| Safety-driven change | Canonical safety policy governs; record Safety rather than manual takeover. |
| Stale/old-generation consequence | Cannot grant, verify, hand back, or steal new-generation authority; current contradictory evidence may still block safety permission. |
| Command/control failure | Rejected delivery, timeout, or exhausted convergence; fault/recover without inventing an External owner. |
| Legitimate lifecycle transition | Explicit current handoff or acquisition boundary; preserve compatible body origin, replace only incompatible domain grants. |

Positive operator evidence may be an explicit request through an exposed PoolOS
control, with its semantic operation and request identity; or a trusted upstream
command/action record that positively identifies an operator's ICP/OCP request,
target, value, ordering and body. A reviewed durable override record may preserve
that evidence across restart, but cannot be reconstructed from current values.
HomeKit inherits the semantics of the exposed PoolOS control, not a blanket
"manual" classification. Policy edits, Reset and session controls are distinct.

Current native snapshot differences (including raw HEATER, PMPCIRC SPEED, actual
RPM and body activity) do not generally identify an actor. Lack of PoolOS
correlation proves only lack of correlation. A body-Off value alone may require
immediate cessation of dependent work and break continuity, but does not prove
who requested it. A body-Off/On observation pair cannot resurrect the old body
session. A native schedule is not automatically an identified human command.
No timing heuristic, off-baseline RPM, source mismatch, or notification label is
sufficient positive operator evidence. Unsupported origin remains explicitly
ambiguous and observable. Future native-intent adapters must prove their evidence
contract; deterministic tests may inject positive evidence but must not imply the
current telemetry transport supplies it.

Positive intent wins a conflicting normal PoolOS command in the affected domain,
even in a priming/handoff window. Final dispatch must recheck the intent revision
under the existing command lock. Already-dispatched commands cannot be unsent;
late consequences cannot cancel the operator record or verify a replacement
operation. Reobserve and reconcile safely without a command fight.

## 3. Bounded convergence and recovery

A convergence episode binds authority generation, body-session identity, domain,
equipment/discovery identity, originating operation or unexplained-drift event,
policy revision, target, start time, absolute deadline and finite correction
budget. Expected physical stages and their prerequisite evidence are explicit.
The sequence `3450 -> 3000 -> 2880 -> 2900` may be a bounded native consequence
of activation or a speed transition. It is not a blanket exemption for arbitrary
values, an opportunity to verify an earlier operation against a future planner
target, or a way to suppress positive manual intent.

For unexplained `2900 -> 3200`, or persistent `2550` against `2600`, retain valid
PUMP origin, enter degraded/reconciling, and permit correction only through current
policy, hydraulic safety and exact final authorization. Configured PMPCIRC and
actual RPM remain separate observations. Exact configured-speed requirements,
commissioned actual-RPM tolerance, observation freshness, acceptance chronology,
priming holds and strict post-command verification are not relaxed.

Reevaluation, duplicate snapshots, plan ID churn, reconnect, and repeated same-value
callbacks must not reset an episode's deadline or replenish its attempt budget.
A retry has a distinct operation ID within the original bounded recovery episode;
it cannot replay an uncertain in-flight operation. Verification is causal and
idempotent. Exhaustion yields a specific control/convergence fault, never External.
New work requires a named recovery boundary, not another refresh pretending to be
a new purpose. Positively attributable operator-assisted exact hand-back may
resolve the fault after fresh verification (scenario 89).

Awaiting evidence is command-free when required facts are unusable. Authoritative
native observations and current policy/intent events drive reevaluation through
the existing coordinator; observations are not command permission. Recovery must
publish the missing evidence, fixed episode status and next eligible transition.
If evidence never returns, remain safely blocked and observable, with the existing
observation-health/recovery path and operator Reset available; do not manufacture
progress or renew indefinite correction authority. New polling loops and sleeps
are not authorized by this specification. Implementation must define and test
finite correction counts and deadlines before enabling correction.

## 4. Solar requested, selected, active and delivering heat

Keep separate requested persistent thermal policy, current requested source,
verified native selected source (`H0002` for Solar), physical `solar.active`,
actual useful heat delivery, preparatory circulation, Solar operating RPM and
source termination. H0002 verification proves selection only. Solar Active is
engagement evidence, not proof of useful net heating; current thermal policy
still evaluates water/collector conditions and target demand.

Solar operating RPM applies when Solar is physically active (scenarios 5, 28–31,
43–45, 76). Before engagement use the appropriate preparation/ordinary requirement
and independently justified protection floors. Do not rename Solar operating RPM
as a safety floor to evade this contract. Preserve required flow and protection
before source activation; implementation must reconcile the existing pre-source
pump ordering with a distinct, justified preparation requirement. Incompatible
equipment safety evidence blocks activation, not the safety prerequisite itself.

IntelliCenter withholding or dropping Solar Active while H0002 remains selected
does not establish operator takeover or failed source delivery. Reevaluate native
engagement and purpose, retain valid origin, and either continue bounded
observation, use an eligible successor, or terminate under policy. Environmental
non-engagement is different from rejected SetHeatMode or failure to verify H0002.
Native disengagement plus a subsequent RPM change must be assessed together under
current purpose and provenance, not converted into manual intent.

Retain the v0.11.23 cold-start safety ordering when H0002 is already armed:
source Off -> authoritative Off verification -> body activation/ordinary
circulation -> later deliberate eligible Solar selection. No incidental Solar
engagement may be treated as evidence PoolOS deliberately selected it.

## 5. Body lifecycle and nested execution purposes

Represent one continuous physical body session independently of nested probe,
filtration, Solar preparation, Solar operation, successor and cleanup executions.
Body identity, equipment generation and activation/adoption origin bind continuity.
An execution purpose, target revision or plan ID may change without a new physical
body activation. The old execution must still stop when no longer current.
Preserving body origin never authorizes its obsolete next command.

Compatible internal transitions use typed transfers with the exact predecessor,
successor, generation, current intent, verified continuity and relevant domain
grants. A successor must be independently authorized. Pump/source receipts remain
operation-specific; incompatible requirements acquire new grants/receipts through
their legitimate path. No arbitrary copying into fresh unrelated leases.
Filtration <-> Solar preserves compatible BODY lifecycle; neither may command
the other's circulation concurrently. An inactive or different body, broken
topology, reset/restart, stale generation, or incompatible operator intent defeats
continuation. Pool origin never authorizes Hot Tub cleanup.

An internal waiting interval retains responsibility only with a typed current
continuity/termination record and no unsafe command permission. Cleanup cannot be
abandoned merely because evidence capture was attempted. Transfer the exact
residual before consuming it, or consume after verified completion or explicit
typed invalidation. Waiting preserves fixed origin time and generation; it does
not renew evidence. Source-only/no-supported-circulation terminal disposal does
not synthesize body or pump authority. Historical no-body-origin restrictions
remain until a reviewed prospective adoption explicitly provides completion scope.

Thermal completion selects only an actually authorized higher-priority successor
within commissioned scope, otherwise immediately required canonical filtration,
otherwise source Off -> body Off -> verified pump 0. Debt alone is not immediate
circulation need. Body-Off acknowledgment or observation alone is insufficient to
claim the full pump-zero endpoint. Continued nonzero RPM requires observation and
reviewed recovery, not a newly invented generic StopPump operation. Manual PUMP
or THERMAL overrides do not transfer BODY completion responsibility. A reviewed
completion reduction may end the owned/adopted body session and its overrides;
it must make the source/hydraulics safe through explicit completion authority,
not silently reclaim normal THERMAL control. User Hot Tub target satisfaction
ends heating demand, not the requested Hot Tub body session.

## 6. Manual scope, expiry and hand-back

An override records positive evidence ID, body/domain, value/request, observed and
request times, authority/policy generation, applicable semantic purpose/session,
and explicit expiry/hand-back rule. PUMP-only leaves BODY/THERMAL unchanged;
THERMAL-only leaves BODY/PUMP unchanged; simultaneous PUMP+THERMAL leaves BODY
unchanged. Pump requirements still follow safe actual operation when Thermal is
manual. Genuine safety minima remain mandatory.

PUMP override expires at the next legitimate operating-purpose/session boundary
or positively attributable exact desired-setpoint hand-back. THERMAL Gas/Solar/Off
normally lasts the current body session or until explicit exact desired-state
hand-back. Environmental Solar eligibility loss does not cancel manual Gas.
A pump-purpose change alone must not erase a still-applicable Thermal override.
The comparison for hand-back is PoolOS's exact current requirement, not an old
target or merely the configured baseline. Verify authoritative resulting state;
equal telemetry without positive hand-back evidence creates no new authority.

Positive Body OFF cancels that body session/opportunity, not future independent
autonomy or the other body. Record the canceled semantic opportunity so the same
Solar opportunity cannot restart on reevaluation. A new independent TOU debt
window or later legitimate opportunity may start a new generation; clock/ID churn
alone cannot. Explicit later same-body ON clears applicable Resume suppression
without fabricating PoolOS activation origin. Persistent operator restraint remains
distinct from one-session cancellation.

HA persistent policy and target changes remain durable, including target changes
from ICP/OCP via the canonical native target path. Positively recognized ICP/OCP
Solar Preferred is a durable policy gesture, distinct from session-scoped Gas,
Solar or Off. Use existing policy storage, not a second target/configuration
database. Seeing SOLARPREF selected without origin evidence must not invent an
operator gesture. Recognition must specify the native evidence limitation.

## 7. Prospective adoption and restart

Adoption records a fresh authority generation and `adopted_at`, independent
current reason/opportunity, body-session and equipment identity, domain scope,
policy revision, authoritative evidence identities, applicable restraints,
and permitted continuation/completion. It is never an accepted historical command.
Fresh current observations must establish safe exclusive topology, configured and
actual state, source and required hydraulic evidence. Retained positive operator
restrictions limit adoption. Equal hardware alone is never enough.

Eligible bases include independently justified filtration or Solar, and execution
of an explicit current user Hot Tub request. Adopt only domains justified by that
reason, respecting separate source/pump overrides. Adoption may grant BODY
completion prospectively without unnecessary OFF/ON or a no-op command pretending
to create historical activation provenance. User Hot Tub adoption preserves its
maintain-until-OFF semantics; opportunistic Hot Tub remains a separate policy.

Restart/reload invalidates old live commands, expectations and cleanup grants.
Fresh adoption may follow current independent policy and verified evidence;
restored old receipts never authorize it. Preserve versioned bounded durable
policy, accounting and positively identified still-applicable manual intent.
Do not persist a reusable live command queue or guess override intent from RPM.
Long-downtime Hot Tub intent must expire or enter explicit recovery; physical Spa
On is not proof of a current user request. Safe reduction still requires an
explicit reviewed recovery grant. No independent reason means None/Unowned (or
External if positively known), with observable recovery/Reset, not adoption solely
to shut equipment down.

## 8. Reset PoolOS Control

Reset is an explicit operator recovery request, distinct from health-incident
acknowledgment, Resume, gate toggling or ordinary autonomy. It creates a new
authority generation synchronously, fences queued normal commands at the final
gateway, and invalidates old session authority and overrides. In-flight effects
must be reobserved; old callbacks cannot verify new reset work or resurrect origin.

Preserve policy/configuration, targets, pump baselines, filtration debt/credit,
TOU rules and safety settings. Under an explicit reviewed reset reduction scope,
make heat/source state safe, drive Hot Tub/Pool Off as needed, and verify body Off
and pump 0. Already verified safe equipment needs no cycling. Reset supplies a
new recovery request, not a fake receipt or unrestricted physical API.

Maintenance, controller mode, equipment identity, hydraulic safety, allowlists,
freshness and post-command chronology still apply. Where evidence is unusable,
only an independently authorized safe reduction may proceed; if none is safe,
wait without commands in WAITING_FOR_FRESH_EVIDENCE. Never guess that shutting
equipment off is safe. After verified baseline and fresh observations, reevaluate
current policy and acquire a fresh session only if currently justified. Do not
restore the old Hot Tub session or pre-reset desired-state snapshot.

## 9. Safety and observability

Safety authority outranks normal and operator control while its requirement is
active (scenarios 79–80). A completed one-time protective action is not permission
to ignore a still-active mandatory safety constraint. Safety clear triggers fresh
evaluation of reality, policy and still-valid positive operator intent; never
restore pre-outage commands. This supersedes the older blanket same-outage manual
exception, without adding any physical safety operation in Stage 1.

Expose one bounded canonical ownership snapshot to HA: current BODY/PUMP/THERMAL
owners and reasons; historical origin kind separately; authority/body/execution
generations; active purpose; desired/actual values; pending verification and fixed
convergence status; last accepted command and verified consequence; latest positive
operator evidence or ambiguity; per-domain override scope and expiry/hand-back;
transition and terminal reason; permission denial; recovery/Reset state and next
eligible recovery event. A historical receipt-presence boolean is not a current
owner. Diagnostics never actuate or become another authority store.

## 10. Preservation and implementation gates

Preserve one physical gateway, exact immutable execution IDs, dynamic PMPCIRC/body
binding, exclusive circulation arbitration, strict acceptance/verification
chronology, fixed holds/deadlines, no replay, no cross-body provenance, no equality
adoption, safety/maintenance gates and canonical filtration accounting. Test the
full day through the HA/native composition, not only isolated manager helpers.
Each scenario requires deterministic assertions for authority, provenance,
command ledger, recovery and physical endpoint as applicable. Test positive intent
and identical telemetry without it separately. Existing green tests and a populated
matrix are not contract compliance or physical commissioning.
