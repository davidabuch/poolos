"""Type-directed dispatch boundary for PoolOS work items."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .commands import Command
from .execution import ExecutionEngine
from .integration import PoolOperation


WorkHandler = Callable[[Any], Any]
PoolOperationHandler = Callable[[PoolOperation], Any]


class UnsupportedWorkItemError(TypeError):
    """Raised when no dispatch route accepts a submitted work item."""


@dataclass(slots=True)
class WorkDispatcher:
    """Route normalized work items without teaching consumers every work type.

    Routes are registered by Python type. Exact-type routes take precedence;
    otherwise the work item's method-resolution order is searched so a route
    registered for a stable base type can handle future specialized items.
    """

    _routes: dict[type[Any], WorkHandler] = field(default_factory=dict)

    def register(
        self,
        work_type: type[Any],
        handler: WorkHandler,
        *,
        replace: bool = False,
    ) -> None:
        """Register the handler responsible for one work-item type."""

        if not isinstance(work_type, type):
            raise TypeError("work_type must be a type")
        if not callable(handler):
            raise TypeError("handler must be callable")
        if work_type in self._routes and not replace:
            raise ValueError(
                f"work handler already registered for type: {work_type.__name__}"
            )
        self._routes[work_type] = handler

    def dispatch(self, work_item: Any) -> Any:
        """Route one work item to its most specific registered handler."""

        handler = self._handler_for(type(work_item))
        if handler is None:
            raise UnsupportedWorkItemError(
                f"no work handler registered for type: {type(work_item).__name__}"
            )
        return handler(work_item)

    def supports(self, work_item: Any) -> bool:
        """Return whether a route exists for the supplied work item."""

        return self._handler_for(type(work_item)) is not None

    def _handler_for(self, work_type: type[Any]) -> WorkHandler | None:
        exact = self._routes.get(work_type)
        if exact is not None:
            return exact
        for base_type in work_type.__mro__[1:]:
            handler = self._routes.get(base_type)
            if handler is not None:
                return handler
        return None


def build_work_dispatcher(
    execution: ExecutionEngine,
    *,
    operation_handler: PoolOperationHandler | None = None,
) -> WorkDispatcher:
    """Build a dispatcher for legacy commands and optional PoolOperations.

    Commands continue through the existing :class:`ExecutionEngine`. When an
    operation handler is supplied, one base-type route accepts every canonical
    ``PoolOperation`` subtype without teaching the dispatcher vendor or
    transport details.
    """

    dispatcher = WorkDispatcher()
    dispatcher.register(Command, execution.submit)
    if operation_handler is not None:
        dispatcher.register(PoolOperation, operation_handler)
    return dispatcher


def build_command_dispatcher(execution: ExecutionEngine) -> WorkDispatcher:
    """Build the legacy command-only dispatcher used by the current runtime."""

    return build_work_dispatcher(execution)
