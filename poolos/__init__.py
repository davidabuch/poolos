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
from .default_policies import (
    CirculationSafetyPolicy,
    HeatingDemandPolicy,
    SanitizerCirculationInterlockPolicy,
    build_default_policy_engine,
)
from .execution import (
    CommandExecutor,
    ExecutionEngine,
    ExecutionRecord,
    ExecutionStatus,
)
from .exceptions import (
    DuplicatePolicyError,
    DuplicateRegistrationError,
    PoolOSError,
    UnknownBodyError,
    UnknownEquipmentError,
    UnknownPolicyError,
)
from .kernel import PoolKernel
from .models import BodyState, TemperatureState
from .policies import (
    Policy,
    PolicyContext,
    PolicyEngine,
    PolicyEvaluation,
    PolicyOutcome,
    PolicySuppression,
)
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
