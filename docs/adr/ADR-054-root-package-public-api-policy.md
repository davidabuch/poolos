# ADR-054: Root-Package Public API Policy

## Status

Accepted for Architecture Review AR-1.

## Context

`poolos/__init__.py` historically re-exports a broad cross-section of domain, runtime, planning,
simulation, execution, and recovery types. At the same time, `poolos.__all__` contains only six
enums retained by an early package contract.

Python permits every imported root attribute to be imported directly even when it is absent from
`__all__`. The repository therefore has a small explicit wildcard API and a much larger implicit
compatibility API. Removing or reorganizing those exports without first documenting the distinction
would create unnecessary compatibility risk.

## Decision

PoolOS will distinguish three API levels:

1. **Stable root API** — names explicitly listed in `poolos.__all__`.
2. **Compatibility root API** — existing direct root imports retained temporarily for compatibility.
3. **Subsystem API** — types imported from their defining modules.

Architecture Review AR-1 is documentation and contract hardening only. It does not remove, rename,
move, or deprecate existing exports.

New code should import subsystem types from their defining modules. New root-package re-exports
require an explicit public-API decision.

## Consequences

- existing root imports continue to work;
- wildcard import behavior remains unchanged;
- future cleanup gains an explicit compatibility boundary;
- accidental expansion or contraction of the stable root API becomes test-detectable;
- later subsystem facade or deprecation work can proceed deliberately.

## Non-goals

AR-1 does not:

- reorganize package directories;
- remove historical imports;
- change runtime behavior;
- rename `PoolRuntime` or other runtime concepts;
- change package versioning;
- change Home Assistant or IntelliCenter boundaries;
- enable command delivery or physical actuation.
