# Shutdown ownership matrix

## Scope

This matrix records the source/body/circulation disposition used when a
PoolOS-created body session must end. It implements the accepted ownership
contract without turning physical equality into ownership and without treating
unattributed source selection as operator intent.

The governing distinction is:

- ongoing THERMAL authority controls a heating policy;
- a BODY-session source-cleanup capability is a narrow, monotonic entitlement
  to select `Off` while unwinding a body activation accepted from PoolOS;
- positive operator THERMAL intent is preserved. PoolOS ends its BODY session
  without rewriting the selected source, and the session-scoped override expires
  only after verified body-Off and pump-zero completion.

The cleanup capability can only select `Off`. It cannot select Solar or Gas,
create THERMAL provenance, verify its own consequence, cross a generation or
restart, survive topology loss, or bypass freshness/currentness gates.

## Canonical source disposition

| Selected source/evidence | THERMAL provenance | Positive operator evidence | Source action | Body completion | Filtration handoff |
| --- | --- | --- | --- | --- | --- |
| Off, current and post-boundary | any | any | none | allowed with BODY provenance | allowed with valid BODY/PUMP provenance |
| Off, stale/unusable/pre-boundary | any | any | none | wait for evidence | wait for evidence |
| Solar selected, inactive or active | PoolOS | none | exact `Off`, then verify | after verified Off | after verified Off |
| Solar selected, inactive or active | absent | none | exact BODY-session cleanup `Off`, then verify | after verified Off | after verified Off |
| Gas selected, firing or idle | PoolOS | none | exact `Off`, then verify | after verified Off | after verified Off |
| Gas selected, firing or idle | absent | none | exact BODY-session cleanup `Off`, then verify | after verified Off | after verified Off |
| Solar or Gas selected | any/absent | current exact operator evidence | preserve selection | BODY Off is allowed and ends the session | denied; end the body session first |
| Source still required by current policy | any | none | none | denied | denied |
| Non-Off source, no BODY or THERMAL origin | none | none | none | no authority | no authority |
| Old-generation operator record | any | old generation | ignored as current intent | evaluate current generation normally | evaluate current generation normally |

Solar activity never substitutes for selected-source disposition. `solar.active`
may fall while H0002 stays selected, and Solar may reactivate while the body
remains active. Therefore inactive Solar is not source cleanup. Gas is treated
more conservatively in the same respect: selected-but-idle Gas is not clean.

## BODY/PUMP/THERMAL combinations

| BODY | PUMP | THERMAL | Current source | Required outcome |
| --- | --- | --- | --- | --- |
| PoolOS | PoolOS | PoolOS | non-Off | verified source Off, then filtration handoff or BODY Off/pump 0 |
| PoolOS | PoolOS | none | non-Off, unattributed | BODY-session source Off, then the same successor rule |
| PoolOS | PoolOS | External | non-Off | preserve operator source; BODY Off/pump 0; no continuous filtration handoff |
| PoolOS | External | PoolOS/none | non-Off, no operator Thermal intent | source cleanup remains concept-specific; BODY responsibility remains, Pump writes remain denied unless a typed purpose boundary reacquires it |
| PoolOS | any | External | Off | no source command; BODY completion remains PoolOS responsibility |
| none/External | any | any | any | no BODY shutdown command from residual thermal cleanup |
| stale BODY entitlement | any | any | any | no command; invalidate or await current evidence according to the existing generation/topology contract |

Immediate filtration is a valid continuous successor only when selected source
is authoritatively Off. A positive operator Solar/Gas selection cannot be carried
into ordinary filtration under the same body session because it may reactivate.
The owned body therefore ends; a later independently justified filtration
opportunity may acquire a fresh generation.

## Evidence and progress

Fresh source selection, body topology, shared-hydraulic inventory, grid state,
filtration disposition, entitlement generation, and positive-operator binding
are checked on every epoch and again before verification. Missing or stale facts
authorize nothing. A source-Off delivery is accepted once, then requires a later
authoritative selected-Off observation. BODY Off requires a later body-Off and
actual pump-zero observation. Duplicate epochs cannot duplicate either command.

The previously impossible state was valid BODY/PUMP responsibility, no THERMAL
origin, H0002 selected, and no operator evidence. Circulation required selected
Off while termination refused to create it. The BODY-session cleanup disposition
now supplies exactly that safe reduction and no broader authority.

## Simulator contract

Tests must model selected source and physical activity independently. H0002 may
remain selected while `solar.active` becomes false, may later reactivate, and may
become Off only after an explicit modeled command consequence. Accepted delivery
never changes the simulated hardware by itself.
