"""Vendor-specific domain packages and adapters.

Vendor packages translate a manufacturer's vocabulary into stable PoolOS
concepts. They must not depend on a particular transport such as Home Assistant,
TCP, or RS-485.
"""

from .base import VendorIdentity

__all__ = ["VendorIdentity"]
