"""Public API for the hardware-independent PoolOS domain and kernel."""

from .bodies import Body, BodyRegistry
from .capabilities import Capability
from .clock import Clock, FixedClock, SystemClock
from .commands import Command, CommandAction
from .config import PoolOSConfig
from .enums import (
    BodyType,
    CommandPriority,
    EquipmentType,
    HeatingSource,
    PolicyPriority,
    RecommendationSeverity,
)
from .equipment import Equipment
from .events import EventBus, PoolEvent
from .exceptions import (
    DuplicateRegistrationError,
    PoolOSError,
    UnknownBodyError,
    UnknownEquipmentError,
)
from .kernel import PoolKernel
from .models import BodyState, TemperatureState
from .registry import EquipmentRegistry
from .state import EquipmentState, RuntimeState

# Retain the enum-only list expected by the original Milestone 1 contract test.
# Additional supported symbols remain directly importable from ``poolos``.
__all__ = [
    "BodyType",
    "CommandPriority",
    "EquipmentType",
    "HeatingSource",
    "PolicyPriority",
    "RecommendationSeverity",
]
