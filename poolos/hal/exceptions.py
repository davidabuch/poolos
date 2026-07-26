"""Exceptions raised by the PoolOS hardware abstraction layer."""

class HALError(Exception):
    """Base exception for HAL failures."""


class AdapterNotFoundError(HALError):
    pass


class DuplicateAdapterError(HALError):
    pass


class AdapterStateError(HALError):
    pass


class UnsupportedCapabilityError(HALError):
    pass


class TransportError(HALError):
    pass


class TransportUnavailableError(TransportError):
    pass


class CommandTimeoutError(TransportError):
    pass
