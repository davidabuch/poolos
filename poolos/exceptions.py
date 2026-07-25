"""Exceptions raised by the hardware-independent PoolOS kernel."""


class PoolOSError(Exception):
    """Base class for PoolOS errors."""


class DuplicateRegistrationError(PoolOSError, ValueError):
    """Raised when an identifier is registered more than once."""


class UnknownEquipmentError(PoolOSError, KeyError):
    """Raised when equipment cannot be found in the registry."""


class UnknownBodyError(PoolOSError, KeyError):
    """Raised when a body cannot be found in the registry."""
