"""Definitions and registry for controllable bodies of water."""

from __future__ import annotations

from dataclasses import dataclass, field

from .enums import BodyType
from .exceptions import DuplicateRegistrationError, UnknownBodyError


@dataclass(frozen=True, slots=True)
class Body:
    """A named body of water in one PoolOS installation."""

    id: str
    name: str
    body_type: BodyType
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("body id must not be empty")
        if not self.name.strip():
            raise ValueError("body name must not be empty")


@dataclass(slots=True)
class BodyRegistry:
    """Canonical registry of bodies in a PoolOS installation."""

    _bodies: dict[str, Body] = field(default_factory=dict)

    def register(self, body: Body) -> None:
        if body.id in self._bodies:
            raise DuplicateRegistrationError(f"body already registered: {body.id}")
        self._bodies[body.id] = body

    def get(self, body_id: str) -> Body:
        try:
            return self._bodies[body_id]
        except KeyError as exc:
            raise UnknownBodyError(body_id) from exc

    def all(self) -> tuple[Body, ...]:
        return tuple(self._bodies.values())

    def find_by_type(self, body_type: BodyType) -> tuple[Body, ...]:
        return tuple(body for body in self._bodies.values() if body.body_type is body_type)

    def enabled_bodies(self) -> tuple[Body, ...]:
        return tuple(body for body in self._bodies.values() if body.enabled)
