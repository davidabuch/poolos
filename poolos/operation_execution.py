"""Composition boundary for canonical operation translation and delivery.

The handler in this module coordinates two existing boundaries without
collapsing their responsibilities:

* :class:`OperationTranslationHandler` remains responsible for pure,
  deterministic translation.
* :class:`VendorCommandGateway` remains responsible for endpoint routing and
  one delivery attempt per vendor command.

Multi-command translations are delivered sequentially and fail fast. Partial
progress is returned as an immutable :class:`OperationExecutionResult` so
callers can audit attempted, failed, rejected, and unattempted commands.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .delivery import DeliveryError, DeliveryReceipt, VendorCommandGateway
from .integration import (
    OperationTranslationHandler,
    PoolOperation,
    TranslationResult,
    VendorCommand,
)


@dataclass(frozen=True, slots=True)
class OperationDeliveryContext:
    """Explicit routing and correlation facts for one canonical operation."""

    endpoint_id: str
    correlation_id: str
    timeout: float | None = None

    def __post_init__(self) -> None:
        endpoint_id = self.endpoint_id.strip()
        correlation_id = self.correlation_id.strip()
        if not endpoint_id:
            raise ValueError("endpoint_id must not be empty")
        if not correlation_id:
            raise ValueError("correlation_id must not be empty")
        if self.timeout is not None and self.timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        object.__setattr__(self, "endpoint_id", endpoint_id)
        object.__setattr__(self, "correlation_id", correlation_id)


OperationDeliveryContextProvider = Callable[
    [PoolOperation], OperationDeliveryContext
]


@dataclass(frozen=True, slots=True)
class OperationExecutionResult:
    """Structured outcome for one translated operation delivery sequence.

    ``receipts`` contains every command that returned a delivery receipt,
    including a receipt that rejected the command. If endpoint delivery raised
    a delivery error, ``failed_command`` identifies the command whose attempt
    failed and ``delivery_error`` retains the typed failure. Commands after a
    rejection or failure are listed in ``unattempted_commands``.
    """

    operation: PoolOperation
    translation: TranslationResult
    delivery_context: OperationDeliveryContext
    receipts: tuple[DeliveryReceipt, ...] = ()
    failed_command: VendorCommand | None = None
    delivery_error: DeliveryError | None = None
    unattempted_commands: tuple[VendorCommand, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipts", tuple(self.receipts))
        object.__setattr__(
            self,
            "unattempted_commands",
            tuple(self.unattempted_commands),
        )
        if (self.failed_command is None) != (self.delivery_error is None):
            raise ValueError(
                "failed_command and delivery_error must be supplied together"
            )

    @property
    def attempted_count(self) -> int:
        """Return the number of commands for which delivery was attempted."""

        return len(self.receipts) + int(self.failed_command is not None)

    @property
    def rejected_receipt(self) -> DeliveryReceipt | None:
        """Return the first rejected receipt, if delivery halted on rejection."""

        return next(
            (receipt for receipt in self.receipts if not receipt.accepted),
            None,
        )

    @property
    def completed(self) -> bool:
        """Return whether every translated command was attempted."""

        return not self.unattempted_commands

    @property
    def successful(self) -> bool:
        """Return whether every translated command completed successfully."""

        return (
            self.delivery_error is None
            and self.failed_command is None
            and not self.unattempted_commands
            and all(receipt.accepted for receipt in self.receipts)
            and len(self.receipts) == len(self.translation.commands)
        )


@dataclass(slots=True)
class OperationExecutionHandler:
    """Translate one operation and deliver its commands in deterministic order."""

    translation_handler: OperationTranslationHandler
    gateway: VendorCommandGateway
    delivery_context_provider: OperationDeliveryContextProvider

    def __call__(self, operation: PoolOperation) -> OperationExecutionResult:
        """Translate and deliver one operation using sequential fail-fast rules."""

        context = self.delivery_context_provider(operation)
        if not isinstance(context, OperationDeliveryContext):
            raise TypeError(
                "delivery_context_provider must return OperationDeliveryContext"
            )

        translation = self.translation_handler(operation)
        receipts: list[DeliveryReceipt] = []

        for index, command in enumerate(translation.commands):
            try:
                receipt = self.gateway.deliver(
                    context.endpoint_id,
                    command,
                    correlation_id=context.correlation_id,
                    timeout=context.timeout,
                )
            except DeliveryError as error:
                return OperationExecutionResult(
                    operation=operation,
                    translation=translation,
                    delivery_context=context,
                    receipts=tuple(receipts),
                    failed_command=command,
                    delivery_error=error,
                    unattempted_commands=translation.commands[index + 1 :],
                )

            receipts.append(receipt)
            if not receipt.accepted:
                return OperationExecutionResult(
                    operation=operation,
                    translation=translation,
                    delivery_context=context,
                    receipts=tuple(receipts),
                    unattempted_commands=translation.commands[index + 1 :],
                )

        return OperationExecutionResult(
            operation=operation,
            translation=translation,
            delivery_context=context,
            receipts=tuple(receipts),
        )
