"""Shared freshness contracts for authoritative native IntelliCenter evidence.

The independent native transport targets a 90-second keepalive cadence and the
Home Assistant coordinator adds a 30-second scheduling/reconciliation margin.
Steady-state ownership must therefore tolerate one full native cadence plus one
margin without treating unchanged good evidence as lost.

Post-delivery verification remains intentionally stricter elsewhere because a
new command consequence must be proven by a later observation.
"""

from __future__ import annotations

from datetime import timedelta

from .observations import FreshnessPolicy

NATIVE_SOURCE_CADENCE = timedelta(seconds=90)
NATIVE_SCHEDULING_MARGIN = timedelta(seconds=30)
NATIVE_STEADY_STATE_FRESHNESS = FreshnessPolicy(
    max_age=NATIVE_SOURCE_CADENCE + NATIVE_SCHEDULING_MARGIN
)

__all__ = [
    "NATIVE_SCHEDULING_MARGIN",
    "NATIVE_SOURCE_CADENCE",
    "NATIVE_STEADY_STATE_FRESHNESS",
]
