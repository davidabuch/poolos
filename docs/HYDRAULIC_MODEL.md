# PoolOS Hydraulic Model

PoolOS separates bodies of water from hydraulic routes.

A route may be simple (`pool`, `spa`, `spillway`) or detailed enough to list
suction sources, return destinations, valve positions, required equipment,
minimum flow, and minimum pump RPM.

This allows simple residential configuration now without blocking future
support for complex commercial plumbing.

Features reference routes and equipment. For example, a waterfall feature may
require a waterfall route, one valve, and a minimum pump speed. The planner can
therefore determine whether the feature can coexist with heating, cleaning, or
another route before commands reach hardware.
