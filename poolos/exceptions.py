"""Exceptions raised by the hardware-independent PoolOS kernel."""


class PoolOSError(Exception):
    """Base class for PoolOS errors."""


class DuplicateRegistrationError(PoolOSError, ValueError):
    """Raised when an identifier is registered more than once."""


class UnknownEquipmentError(PoolOSError, KeyError):
    """Raised when equipment cannot be found in the registry."""


class UnknownBodyError(PoolOSError, KeyError):
    """Raised when a body cannot be found in the registry."""


class DuplicatePolicyError(PoolOSError, ValueError):
    """Raised when a policy identifier is registered more than once."""


class UnknownPolicyError(PoolOSError, KeyError):
    """Raised when a policy cannot be found in the policy engine."""


class DuplicatePlanningStrategyError(PoolOSError):
    """Raised when a planning strategy type is registered more than once."""


class PlanningStrategyNotFoundError(PoolOSError):
    """Raised when no strategy supports a requested objective type."""


class PlanNotFoundError(PoolOSError):
    """Raised when a requested plan ID is unknown."""
