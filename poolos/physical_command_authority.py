"""Fail-closed authority and native-consequence correlation for physical writes.

This boundary is vendor-neutral.  It owns no transport and cannot deliver a
command.  Delivery adapters use it twice: once before queueing and again at the
physical dispatch edge.  Native observation code consumes the bounded
expectations without changing authoritative equipment truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
import math
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4

from .operating_baselines import PumpOperatingBaselines
from .intellicenter_readonly import is_pmpcirc_native_id


class PhysicalRequestSource(StrEnum):
    """Origin category for one PoolOS physical mutation request."""

    MANUAL = "manual"
    AUTONOMOUS = "autonomous"
    AUTOMATIC_THERMAL = "automatic_thermal"
    AUTOMATIC_FILTRATION = "automatic_filtration"
    RECONCILIATION = "reconciliation"
    SAFETY_INTERLOCK = "safety_interlock"
    GRID_OUTAGE_SAFETY = "grid_outage_safety"


class PhysicalAuthorityReason(StrEnum):
    """Stable reason for a physical authority decision."""

    ALLOWED = "allowed"
    AUTHORITY_UNRESOLVED = "authority_unresolved"
    MAINTENANCE_MODE = "maintenance_mode"
    CONTROLLER_MODE_UNRESOLVED = "controller_mode_unresolved"
    CONTROLLER_SERVICE_MODE = "controller_service_mode"
    CONTROLLER_TIMEOUT_MODE = "controller_timeout_mode"
    AUTOMATIC_THERMAL_GATE_DISABLED = "automatic_thermal_gate_disabled"
    THERMAL_LIVE_GATE_DISABLED = "thermal_live_gate_disabled"
    AUTOMATIC_THERMAL_SCOPE_DISABLED = "automatic_thermal_scope_disabled"
    AUTOMATIC_THERMAL_SCOPE_MISMATCH = "automatic_thermal_scope_mismatch"
    AUTOMATIC_THERMAL_CONTEXT_MISSING = "automatic_thermal_context_missing"
    AUTOMATIC_THERMAL_CONTEXT_STALE = "automatic_thermal_context_stale"
    AUTOMATIC_THERMAL_DRIVER_UNLOADED = "automatic_thermal_driver_unloaded"
    AUTOMATIC_THERMAL_OPERATION_UNAUTHORIZED = (
        "automatic_thermal_operation_unauthorized"
    )
    POOL_AUTOMATIC_CONTROL_SUPPRESSED = "pool_automatic_control_suppressed"
    SPA_AUTOMATIC_CONTROL_SUPPRESSED = "spa_automatic_control_suppressed"
    AUTOMATIC_RESTRAINT_RESTORATION_PENDING = (
        "automatic_restraint_restoration_pending"
    )
    AUTOMATIC_FILTRATION_GATE_DISABLED = "automatic_filtration_gate_disabled"
    AUTOMATIC_FILTRATION_CONTEXT_MISSING = "automatic_filtration_context_missing"
    AUTOMATIC_FILTRATION_CONTEXT_STALE = "automatic_filtration_context_stale"
    AUTOMATIC_FILTRATION_OPERATION_UNAUTHORIZED = (
        "automatic_filtration_operation_unauthorized"
    )
    AUTOMATIC_FILTRATION_DRIVER_UNLOADED = "automatic_filtration_driver_unloaded"
    GRID_OUTAGE_GATE_DISABLED = "grid_outage_gate_disabled"
    GRID_OUTAGE_CONTEXT_MISSING = "grid_outage_context_missing"
    GRID_OUTAGE_CONTEXT_STALE = "grid_outage_context_stale"
    GRID_OUTAGE_OPERATION_UNAUTHORIZED = "grid_outage_operation_unauthorized"
    GRID_OUTAGE_DRIVER_UNLOADED = "grid_outage_driver_unloaded"
    MANUAL_PUMP_SESSION_STALE = "manual_pump_session_stale"


class GridOutageDispatchPurpose(StrEnum):
    """Exact reduction-only purpose at the final physical boundary."""

    SPA_SOURCE_OFF = "spa_source_off"
    POOL_SOURCE_OFF = "pool_source_off"
    POOL_LIGHT_OFF = "pool_light_off"
    JETS_OFF = "jets_off"
    SLIDE_OFF = "slide_off"
    WATERFALL_OFF = "waterfall_off"
    SPA_BODY_OFF = "spa_body_off"
    POOL_PUMP_REDUCTION = "pool_pump_reduction"


_GRID_OUTAGE_SHAPES: Mapping[
    GridOutageDispatchPurpose,
    tuple[str, str, bool | int | str],
] = MappingProxyType(
    {
        GridOutageDispatchPurpose.SPA_SOURCE_OFF: (
            "body_heat_source",
            "B1202",
            "00000",
        ),
        GridOutageDispatchPurpose.POOL_SOURCE_OFF: (
            "body_heat_source",
            "B1101",
            "00000",
        ),
        GridOutageDispatchPurpose.POOL_LIGHT_OFF: (
            "circuit_active",
            "C0002",
            False,
        ),
        GridOutageDispatchPurpose.JETS_OFF: (
            "circuit_active",
            "C0003",
            False,
        ),
        GridOutageDispatchPurpose.SLIDE_OFF: (
            "circuit_active",
            "C0004",
            False,
        ),
        GridOutageDispatchPurpose.WATERFALL_OFF: (
            "circuit_active",
            "FTR01",
            False,
        ),
        GridOutageDispatchPurpose.SPA_BODY_OFF: (
            "body_active",
            "B1202",
            False,
        ),
    }
)


@dataclass(frozen=True, slots=True)
class GridOutageDispatchAuthority:
    """One registered candidate in one current confirmed-outage frame."""

    generation: int
    outage_epoch_id: str
    frame_identity: str
    candidate_id: str
    purpose: GridOutageDispatchPurpose
    operation: str
    target: str
    requested_value: bool | int | str
    policy_fingerprint: str = PumpOperatingBaselines().fingerprint
    runtime_binding: str = ""

    def __post_init__(self) -> None:
        if self.generation < 1:
            raise ValueError("outage authority generation must be positive")
        for name in (
            "outage_epoch_id",
            "frame_identity",
            "candidate_id",
            "operation",
            "target",
            "policy_fingerprint",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        object.__setattr__(self, "purpose", GridOutageDispatchPurpose(self.purpose))
        allowed = (
            self.operation == "pump_circuit_speed"
            and is_pmpcirc_native_id(self.target)
            and type(self.requested_value) is int
            and self.requested_value > 0
            if self.purpose is GridOutageDispatchPurpose.POOL_PUMP_REDUCTION
            else _grid_outage_shape_matches(
                self.operation,
                self.target,
                self.requested_value,
                _GRID_OUTAGE_SHAPES[self.purpose],
            )
        )
        if not allowed:
            raise ValueError(
                "outage authority does not match exact reduction envelope"
            )


@dataclass(frozen=True, slots=True)
class GridOutageDispatchContext:
    """Immutable final-gateway binding for one outage candidate."""

    generation: int
    outage_epoch_id: str
    frame_identity: str
    candidate_id: str
    authority: GridOutageDispatchAuthority

    def __post_init__(self) -> None:
        if (
            self.generation != self.authority.generation
            or self.outage_epoch_id != self.authority.outage_epoch_id
            or self.frame_identity != self.authority.frame_identity
            or self.candidate_id != self.authority.candidate_id
        ):
            raise ValueError("outage dispatch context does not match authority")


class AutomaticThermalDispatchPurpose(StrEnum):
    """Final-gateway authority class for normal work versus reduction only."""

    NORMAL = "normal"
    POOL_TEMPERATURE_PROBE = "pool_temperature_probe"
    TERMINATION = "termination"
    CIRCULATION_BODY_CLEANUP = "circulation_body_cleanup"
    CIRCULATION_PUMP_NORMALIZATION = "circulation_pump_normalization"


@dataclass(frozen=True, slots=True)
class AutomaticThermalCleanupAuthority:
    """Exact one-epoch cleanup operation admitted by canonical supervision."""

    generation: int
    epoch_identity: str
    candidate_identity: str
    body: str
    purpose: AutomaticThermalDispatchPurpose
    operation: str
    target: str
    requested_value: bool | int | str

    def __post_init__(self) -> None:
        if self.generation < 1:
            raise ValueError("cleanup authority generation must be positive")
        for name in ("epoch_identity", "candidate_identity", "body", "operation", "target"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        object.__setattr__(self, "purpose", AutomaticThermalDispatchPurpose(self.purpose))
        if self.purpose is AutomaticThermalDispatchPurpose.CIRCULATION_BODY_CLEANUP:
            expected_target = "B1101" if self.body == "pool" else "B1202"
            if not (
                self.operation == "body_active"
                and self.body in {"pool", "hot_tub"}
                and self.target == expected_target
                and self.requested_value is False
            ):
                raise ValueError("body cleanup authority must be exact owned-body Off")
        elif self.purpose is AutomaticThermalDispatchPurpose.CIRCULATION_PUMP_NORMALIZATION:
            if not (
                self.body == "pool"
                and self.operation == "pump_circuit_speed"
                and is_pmpcirc_native_id(self.target)
                and isinstance(self.requested_value, int)
                and not isinstance(self.requested_value, bool)
                and self.requested_value > 0
            ):
                raise ValueError("pump cleanup authority must bind one positive Pool RPM")
        else:
            raise ValueError("unsupported circulation cleanup authority purpose")


@dataclass(frozen=True, slots=True)
class AutomaticThermalProbeAuthority:
    """Exact one-epoch Pool probe operation admitted by supervision."""

    generation: int
    epoch_identity: str
    operation_id: str
    operation: str
    target: str
    requested_value: bool | int | str
    policy_fingerprint: str = PumpOperatingBaselines().fingerprint

    def __post_init__(self) -> None:
        if self.generation < 1:
            raise ValueError("probe authority generation must be positive")
        for name in (
            "epoch_identity",
            "operation_id",
            "operation",
            "target",
            "policy_fingerprint",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        allowed = (
            self.operation == "body_active"
            and self.target == "B1101"
            and self.requested_value is True
        ) or (
            self.operation == "body_heat_source"
            and self.target == "B1101"
            and self.requested_value == "00000"
        ) or (
            self.operation == "pump_circuit_speed"
            and is_pmpcirc_native_id(self.target)
            and type(self.requested_value) is int
            and self.requested_value > 0
        )
        if not allowed:
            raise ValueError("unsupported Pool temperature-probe operation")


@dataclass(frozen=True, slots=True)
class AutomaticThermalDispatchContext:
    """Restrictive one-epoch authority proof for automatic thermal delivery."""

    generation: int
    epoch_identity: str
    session_identity: str
    body: str
    pump_circuit_id: str | None = None
    operating_purpose: str | None = None
    purpose: AutomaticThermalDispatchPurpose = AutomaticThermalDispatchPurpose.NORMAL
    cleanup_authority: AutomaticThermalCleanupAuthority | None = None
    probe_authority: AutomaticThermalProbeAuthority | None = None
    policy_fingerprint: str = PumpOperatingBaselines().fingerprint
    runtime_binding: str = ""
    pump_session_id: str | None = None
    effective_pump_rpm: int | None = None

    def __post_init__(self) -> None:
        if self.generation < 1:
            raise ValueError("automatic thermal generation must be positive")
        for name in ("epoch_identity", "session_identity", "body"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if not self.policy_fingerprint.strip():
            raise ValueError("pump policy fingerprint must not be empty")
        if self.body not in {"pool", "hot_tub"}:
            raise ValueError("unsupported automatic thermal body")
        object.__setattr__(
            self,
            "purpose",
            AutomaticThermalDispatchPurpose(self.purpose),
        )
        if self.pump_circuit_id is not None and not is_pmpcirc_native_id(
            self.pump_circuit_id
        ):
            raise ValueError(
                "automatic thermal pump circuit must be a concrete p01xx identity"
            )
        if self.operating_purpose is not None and self.operating_purpose not in {
            "temperature_acquisition",
            "ordinary_circulation",
            "solar_heating",
            "gas_heating",
            "priming",
        }:
            raise ValueError("unsupported thermal operating purpose")
        if (self.pump_session_id is None) != (self.effective_pump_rpm is None):
            raise ValueError("pump session identity and effective RPM must be paired")
        cleanup_purposes = {
            AutomaticThermalDispatchPurpose.CIRCULATION_BODY_CLEANUP,
            AutomaticThermalDispatchPurpose.CIRCULATION_PUMP_NORMALIZATION,
        }
        if self.purpose in cleanup_purposes:
            if self.cleanup_authority is None:
                raise ValueError("cleanup dispatch requires exact cleanup authority")
            if (
                self.cleanup_authority.generation != self.generation
                or self.cleanup_authority.epoch_identity != self.epoch_identity
                or self.cleanup_authority.body != self.body
                or self.cleanup_authority.purpose is not self.purpose
            ):
                raise ValueError("cleanup dispatch context does not match authority")
        elif self.purpose is AutomaticThermalDispatchPurpose.POOL_TEMPERATURE_PROBE:
            if (
                self.body != "pool"
                or self.probe_authority is None
                or self.cleanup_authority is not None
                or self.probe_authority.generation != self.generation
                or self.probe_authority.epoch_identity != self.epoch_identity
                or self.probe_authority.policy_fingerprint
                != self.policy_fingerprint
            ):
                raise ValueError("probe dispatch requires exact current Pool authority")
        elif self.cleanup_authority is not None or self.probe_authority is not None:
            raise ValueError("normal or source termination context cannot carry cleanup authority")


class AutomaticFiltrationDispatchPurpose(StrEnum):
    """Exact Pool-only filtration operation class."""

    NORMAL = "normal"
    OWNED_BODY_CLEANUP = "owned_body_cleanup"


@dataclass(frozen=True, slots=True)
class AutomaticFiltrationDispatchContext:
    """Immutable final-gateway binding for one filtration operation."""

    generation: int
    epoch_identity: str
    session_identity: str
    operation_identity: str
    operation: str
    target: str
    requested_value: bool | int
    pump_circuit_id: str
    ownership_lease_id: str | None = None
    body_activation_receipt_id: str | None = None
    purpose: AutomaticFiltrationDispatchPurpose = (
        AutomaticFiltrationDispatchPurpose.NORMAL
    )
    policy_fingerprint: str = PumpOperatingBaselines().fingerprint
    runtime_binding: str = ""
    pump_session_id: str | None = None
    effective_pump_rpm: int | None = None

    def __post_init__(self) -> None:
        if self.generation < 1:
            raise ValueError("automatic filtration generation must be positive")
        for name in (
            "epoch_identity",
            "session_identity",
            "operation_identity",
            "operation",
            "target",
            "pump_circuit_id",
            "policy_fingerprint",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if not is_pmpcirc_native_id(self.pump_circuit_id):
            raise ValueError("automatic filtration requires a concrete Pool PMPCIRC")
        if (self.pump_session_id is None) != (self.effective_pump_rpm is None):
            raise ValueError("pump session identity and effective RPM must be paired")
        object.__setattr__(
            self,
            "purpose",
            AutomaticFiltrationDispatchPurpose(self.purpose),
        )
        if self.purpose is AutomaticFiltrationDispatchPurpose.OWNED_BODY_CLEANUP:
            if not (
                self.ownership_lease_id
                and self.ownership_lease_id.strip()
                and self.body_activation_receipt_id
                and self.body_activation_receipt_id.strip()
            ):
                raise ValueError(
                    "filtration cleanup requires exact body ownership provenance"
                )
        elif (
            self.ownership_lease_id is not None
            or self.body_activation_receipt_id is not None
        ):
            raise ValueError("normal filtration context cannot carry cleanup provenance")
        allowed = (
            self.operation == "body_active"
            and self.target == "B1101"
            and type(self.requested_value) is bool
            and (
                self.requested_value is True
                if self.purpose is AutomaticFiltrationDispatchPurpose.NORMAL
                else self.requested_value is False
            )
        ) or (
            self.purpose is AutomaticFiltrationDispatchPurpose.NORMAL
            and self.operation == "pump_circuit_speed"
            and self.target == self.pump_circuit_id
            and type(self.requested_value) is int
            and self.requested_value > 0
        )
        if not allowed:
            raise ValueError("operation exceeds exact automatic filtration envelope")


@dataclass(frozen=True, slots=True)
class PhysicalCommandRequest:
    """Immutable identity of one proposed physical mutation."""

    operation: str
    target: str
    source: PhysicalRequestSource
    requested_value: bool | int | float | str
    request_id: str = field(default_factory=lambda: str(uuid4()))
    manual_pump_session_id: str | None = None
    automatic_thermal_context: AutomaticThermalDispatchContext | None = None
    automatic_filtration_context: AutomaticFiltrationDispatchContext | None = None
    grid_outage_context: GridOutageDispatchContext | None = None

    def __post_init__(self) -> None:
        if not self.operation.strip() or not self.target.strip():
            raise ValueError("physical command operation and target are required")
        if not self.request_id.strip():
            raise ValueError("physical command request_id is required")
        if self.manual_pump_session_id is not None and not (
            self.source is PhysicalRequestSource.MANUAL
            and self.operation == "pump_circuit_speed"
            and self.manual_pump_session_id.strip()
        ):
            raise ValueError(
                "manual pump session identity requires a manual pump request"
            )
        if (
            self.source is not PhysicalRequestSource.AUTOMATIC_THERMAL
            and self.automatic_thermal_context is not None
        ):
            raise ValueError(
                "automatic thermal context requires automatic thermal source"
            )
        if (
            self.source is not PhysicalRequestSource.GRID_OUTAGE_SAFETY
            and self.grid_outage_context is not None
        ):
            raise ValueError("grid outage context requires grid outage safety source")
        if (
            self.source is not PhysicalRequestSource.AUTOMATIC_FILTRATION
            and self.automatic_filtration_context is not None
        ):
            raise ValueError(
                "automatic filtration context requires automatic filtration source"
            )
        if (
            self.source is PhysicalRequestSource.AUTOMATIC_FILTRATION
            and self.automatic_thermal_context is not None
        ):
            raise ValueError("filtration requests cannot carry thermal context")
        if (
            self.source is PhysicalRequestSource.GRID_OUTAGE_SAFETY
            and self.automatic_thermal_context is not None
        ):
            raise ValueError("grid outage requests cannot carry thermal context")


@dataclass(frozen=True, slots=True)
class ExpectedNativeConsequence:
    """One authoritative native value expected after a PoolOS command."""

    concept: str
    native_object_id: str
    expected_value: bool | int | float | str
    numeric_tolerance: float = 0.0
    retain_matching_updates: bool = False

    def __post_init__(self) -> None:
        if not self.concept.strip() or not self.native_object_id.strip():
            raise ValueError("native consequence concept and object are required")
        if not math.isfinite(self.numeric_tolerance) or self.numeric_tolerance < 0:
            raise ValueError("native consequence tolerance must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class PhysicalAuthorityDecision:
    """One deterministic current authority result."""

    allowed: bool
    reason: PhysicalAuthorityReason
    request: PhysicalCommandRequest
    maintenance_mode: bool | None
    controller_mode: str | None


@dataclass(frozen=True, slots=True)
class NativeConsequenceAttribution:
    """Evidence that an authoritative transition matched a PoolOS expectation."""

    expectation_id: str
    request_id: str
    request_source: PhysicalRequestSource
    operation: str
    target: str


@dataclass(slots=True)
class _PendingExpectation:
    expectation_id: str
    request: PhysicalCommandRequest
    consequence: ExpectedNativeConsequence
    reserved_at: datetime
    expires_at: datetime
    dispatch_started: bool = False


class PhysicalCommandDeniedError(RuntimeError):
    """Raised when current central authority denies physical delivery."""

    def __init__(self, decision: PhysicalAuthorityDecision) -> None:
        self.decision = decision
        super().__init__(f"physical command denied:{decision.reason.value}")


@dataclass(slots=True)
class PoolOSPhysicalCommandAuthority:
    """Central, fail-closed authority and bounded correlation registry."""

    baselines: PumpOperatingBaselines = PumpOperatingBaselines()
    _runtime_binding: str = field(
        default_factory=lambda: uuid4().hex,
        init=False,
        repr=False,
    )
    expectation_ttl: timedelta = timedelta(seconds=45)
    expectation_limit: int = 64
    _maintenance_mode: bool | None = field(default=None, init=False, repr=False)
    _controller_mode: str | None = field(default=None, init=False, repr=False)
    _pool_automatic_control_suppressed: bool = field(
        default=False, init=False, repr=False
    )
    _spa_automatic_control_suppressed: bool = field(
        default=False, init=False, repr=False
    )
    _automatic_restoration_barrier_required: bool = field(
        default=False, init=False, repr=False
    )
    _pool_automatic_restraint_restored: bool = field(
        default=True, init=False, repr=False
    )
    _spa_automatic_restraint_restored: bool = field(
        default=True, init=False, repr=False
    )
    _expectations: dict[str, _PendingExpectation] = field(
        default_factory=dict, init=False, repr=False
    )
    _native_truth: dict[tuple[str, str], Any] = field(
        default_factory=dict, init=False, repr=False
    )
    _pump_session_binding: tuple[str, str, str, str, int] | None = field(
        default=None, init=False, repr=False
    )
    _automatic_thermal_driver_enabled: bool = field(
        default=False, init=False, repr=False
    )
    _automatic_thermal_live_enabled: bool = field(
        default=False, init=False, repr=False
    )
    _automatic_thermal_scope: str = field(
        default="disabled", init=False, repr=False
    )
    _automatic_thermal_loaded: bool = field(default=True, init=False, repr=False)
    _automatic_thermal_generation: int = field(default=0, init=False, repr=False)
    _automatic_thermal_epoch_identity: str | None = field(
        default=None, init=False, repr=False
    )
    _automatic_thermal_session_identity: str | None = field(
        default=None, init=False, repr=False
    )
    _automatic_thermal_cleanup_authority: AutomaticThermalCleanupAuthority | None = field(
        default=None, init=False, repr=False
    )
    _automatic_thermal_probe_authority: AutomaticThermalProbeAuthority | None = field(
        default=None, init=False, repr=False
    )
    _automatic_filtration_gate_enabled: bool = field(
        default=False, init=False, repr=False
    )
    _automatic_filtration_loaded: bool = field(default=True, init=False, repr=False)
    _automatic_filtration_generation: int = field(default=0, init=False, repr=False)
    _automatic_filtration_epoch_identity: str | None = field(
        default=None, init=False, repr=False
    )
    _automatic_filtration_context: AutomaticFiltrationDispatchContext | None = field(
        default=None, init=False, repr=False
    )
    _grid_outage_gate_enabled: bool = field(default=False, init=False, repr=False)
    _grid_outage_loaded: bool = field(default=True, init=False, repr=False)
    _grid_outage_generation: int = field(default=0, init=False, repr=False)
    _grid_outage_epoch_id: str | None = field(default=None, init=False, repr=False)
    _grid_outage_frame_identity: str | None = field(default=None, init=False, repr=False)
    _grid_outage_authority: GridOutageDispatchAuthority | None = field(
        default=None, init=False, repr=False
    )

    def __post_init__(self) -> None:
        if self.expectation_ttl <= timedelta(0):
            raise ValueError("expectation_ttl must be positive")
        if self.expectation_limit <= 0:
            raise ValueError("expectation_limit must be positive")

    @property
    def maintenance_resolved(self) -> bool:
        return self._maintenance_mode is not None

    @property
    def maintenance_mode(self) -> bool | None:
        return self._maintenance_mode

    @property
    def controller_mode(self) -> str | None:
        return self._controller_mode

    @property
    def pool_automatic_control_suppressed(self) -> bool:
        """Return the persistent operator restraint applied to automatic Pool work."""

        return self._pool_automatic_control_suppressed

    def set_pool_automatic_control_suppressed(self, suppressed: bool) -> None:
        """Invalidate queued automatic Pool work whenever the restraint changes."""

        suppressed = bool(suppressed)
        if suppressed == self._pool_automatic_control_suppressed:
            return
        self._pool_automatic_control_suppressed = suppressed
        self._invalidate_automatic_thermal_context()
        self._invalidate_automatic_filtration_context()
        self._invalidate_grid_outage_context()

    @property
    def spa_automatic_control_suppressed(self) -> bool:
        """Return the operator restraint applied only to automatic Spa work."""

        return self._spa_automatic_control_suppressed

    def set_spa_automatic_control_suppressed(self, suppressed: bool) -> None:
        """Invalidate queued automatic Spa work whenever its restraint changes."""

        suppressed = bool(suppressed)
        if suppressed == self._spa_automatic_control_suppressed:
            return
        self._spa_automatic_control_suppressed = suppressed
        self._invalidate_automatic_thermal_context()

    def require_automatic_restraint_restoration(self) -> None:
        """Deny automatic dispatch until both persisted body restraints restore."""

        self._automatic_restoration_barrier_required = True
        self._pool_automatic_restraint_restored = False
        self._spa_automatic_restraint_restored = False
        self._invalidate_automatic_thermal_context()
        self._invalidate_automatic_filtration_context()
        self._invalidate_grid_outage_context()

    def resolve_pool_automatic_control_suppressed(self, suppressed: bool) -> None:
        """Apply restored Pool restraint truth and mark its startup gate complete."""

        self.set_pool_automatic_control_suppressed(suppressed)
        self._pool_automatic_restraint_restored = True
        self._invalidate_automatic_thermal_context()
        self._invalidate_automatic_filtration_context()
        self._invalidate_grid_outage_context()

    def resolve_spa_automatic_control_suppressed(self, suppressed: bool) -> None:
        """Apply restored Spa restraint truth and mark its startup gate complete."""

        self.set_spa_automatic_control_suppressed(suppressed)
        self._spa_automatic_restraint_restored = True
        self._invalidate_automatic_thermal_context()
        self._invalidate_automatic_filtration_context()
        self._invalidate_grid_outage_context()

    def resolve_maintenance(self, enabled: bool) -> None:
        """Resolve persisted state or change the global physical kill switch."""

        changed = self._maintenance_mode is None or self._maintenance_mode != bool(enabled)
        self._maintenance_mode = bool(enabled)
        if changed:
            self.invalidate_expectations()

    def set_controller_mode(self, mode: str | None) -> None:
        """Accept only canonical native controller mode evidence."""

        normalized = None if mode is None else str(mode).strip().casefold()
        accepted = (
            normalized if normalized in {"auto", "service", "timeout"} else None
        )
        changed = accepted != self._controller_mode
        self._controller_mode = accepted
        if changed:
            self.invalidate_expectations()

    def configure_automatic_thermal(
        self,
        *,
        driver_enabled: bool,
        thermal_live_enabled: bool,
        commissioning_scope: str,
    ) -> None:
        """Set restrictive automatic gates and invalidate queued authority."""

        scope = str(commissioning_scope).strip().casefold()
        if scope not in {"disabled", "pool", "hot_tub"}:
            raise ValueError("unsupported automatic thermal commissioning scope")
        changed = (
            self._automatic_thermal_driver_enabled != bool(driver_enabled)
            or self._automatic_thermal_live_enabled != bool(thermal_live_enabled)
            or self._automatic_thermal_scope != scope
        )
        self._automatic_thermal_driver_enabled = bool(driver_enabled)
        self._automatic_thermal_live_enabled = bool(thermal_live_enabled)
        self._automatic_thermal_scope = scope
        if changed:
            self._invalidate_automatic_thermal_context()

    def synchronize_pump_speed_session(
        self,
        *,
        session_id: str | None,
        body: str | None,
        purpose: str | None,
        pump_circuit_id: str | None,
        effective_rpm: int | None,
    ) -> None:
        """Bind exact current pump intent without granting physical authority."""

        values = (session_id, body, purpose, pump_circuit_id, effective_rpm)
        if all(value is None for value in values):
            self._pump_session_binding = None
            return
        if any(value is None for value in values):
            raise ValueError("pump session authority binding must be complete")
        assert session_id is not None
        assert body is not None
        assert purpose is not None
        assert pump_circuit_id is not None
        assert effective_rpm is not None
        if body not in {"pool", "hot_tub"} or effective_rpm <= 0:
            raise ValueError("invalid pump session authority binding")
        self._pump_session_binding = (
            session_id,
            body,
            purpose,
            pump_circuit_id,
            effective_rpm,
        )

    def begin_automatic_thermal_epoch(self, epoch_identity: str) -> None:
        """Invalidate older queued work at each authoritative runtime epoch."""

        if not epoch_identity.strip():
            raise ValueError("automatic thermal epoch identity must not be empty")
        if epoch_identity == self._automatic_thermal_epoch_identity:
            return
        self._automatic_thermal_generation += 1
        self._automatic_thermal_epoch_identity = epoch_identity
        self._automatic_thermal_session_identity = None
        self._automatic_thermal_cleanup_authority = None
        self._automatic_thermal_probe_authority = None

    def register_automatic_thermal_probe(
        self,
        *,
        epoch_identity: str,
        operation_id: str,
        operation: str,
        target: str,
        requested_value: bool | int | str,
    ) -> AutomaticThermalProbeAuthority:
        """Register exactly one current Pool probe operation."""

        if epoch_identity != self._automatic_thermal_epoch_identity:
            raise ValueError("automatic thermal probe epoch is not current")
        if (
            operation == "pump_circuit_speed"
            and requested_value != self.baselines.temperature_probe_rpm
        ):
            raise ValueError("unsupported Pool temperature-probe operation")
        authority = AutomaticThermalProbeAuthority(
            generation=self._automatic_thermal_generation,
            epoch_identity=epoch_identity,
            operation_id=operation_id,
            operation=operation,
            target=target,
            requested_value=requested_value,
            policy_fingerprint=self.baselines.fingerprint,
        )
        self._automatic_thermal_probe_authority = authority
        self._automatic_thermal_cleanup_authority = None
        return authority

    def register_automatic_thermal_cleanup(
        self,
        *,
        epoch_identity: str,
        candidate_identity: str,
        body: str,
        purpose: AutomaticThermalDispatchPurpose,
        operation: str,
        target: str,
        requested_value: bool | int,
    ) -> AutomaticThermalCleanupAuthority:
        """Register one exact current cleanup candidate, without dispatching it."""

        if epoch_identity != self._automatic_thermal_epoch_identity:
            raise ValueError("automatic thermal cleanup epoch is not current")
        authority = AutomaticThermalCleanupAuthority(
            generation=self._automatic_thermal_generation,
            epoch_identity=epoch_identity,
            candidate_identity=candidate_identity,
            body=body,
            purpose=purpose,
            operation=operation,
            target=target,
            requested_value=requested_value,
        )
        self._automatic_thermal_cleanup_authority = authority
        self._automatic_thermal_probe_authority = None
        return authority

    def bind_automatic_thermal_dispatch(
        self,
        *,
        epoch_identity: str,
        session_identity: str,
        body: str,
        pump_circuit_id: str | None = None,
        operating_purpose: str | None = None,
        purpose: AutomaticThermalDispatchPurpose = AutomaticThermalDispatchPurpose.NORMAL,
        cleanup_candidate_identity: str | None = None,
        probe_operation_id: str | None = None,
        pump_session_id: str | None = None,
        effective_pump_rpm: int | None = None,
    ) -> AutomaticThermalDispatchContext:
        """Bind one current session to the latest authoritative epoch."""

        if epoch_identity != self._automatic_thermal_epoch_identity:
            raise ValueError("automatic thermal epoch is not current")
        if not session_identity.strip():
            raise ValueError("automatic thermal session identity must not be empty")
        if body not in {"pool", "hot_tub"}:
            raise ValueError("unsupported automatic thermal body")
        purpose = AutomaticThermalDispatchPurpose(purpose)
        cleanup = None
        probe = None
        if purpose in {
            AutomaticThermalDispatchPurpose.CIRCULATION_BODY_CLEANUP,
            AutomaticThermalDispatchPurpose.CIRCULATION_PUMP_NORMALIZATION,
        }:
            cleanup = self._automatic_thermal_cleanup_authority
            if (
                cleanup is None
                or cleanup_candidate_identity != cleanup.candidate_identity
                or cleanup.epoch_identity != epoch_identity
                or cleanup.body != body
                or cleanup.purpose is not purpose
            ):
                raise ValueError("automatic thermal cleanup candidate is not current")
        elif cleanup_candidate_identity is not None:
            raise ValueError("cleanup candidate requires cleanup dispatch purpose")
        if purpose is AutomaticThermalDispatchPurpose.POOL_TEMPERATURE_PROBE:
            probe = self._automatic_thermal_probe_authority
            if (
                probe is None
                or probe_operation_id != probe.operation_id
                or probe.epoch_identity != epoch_identity
                or body != "pool"
            ):
                raise ValueError("automatic thermal probe operation is not current")
        elif probe_operation_id is not None:
            raise ValueError("probe operation requires probe dispatch purpose")
        self._automatic_thermal_session_identity = session_identity
        return AutomaticThermalDispatchContext(
            generation=self._automatic_thermal_generation,
            epoch_identity=epoch_identity,
            session_identity=session_identity,
            body=body,
            pump_circuit_id=pump_circuit_id,
            operating_purpose=operating_purpose,
            purpose=purpose,
            cleanup_authority=cleanup,
            probe_authority=probe,
            policy_fingerprint=self.baselines.fingerprint,
            runtime_binding=self._runtime_binding,
            pump_session_id=pump_session_id,
            effective_pump_rpm=effective_pump_rpm,
        )

    def unload_automatic_thermal_driver(self) -> None:
        """Make all late automatic work inert without issuing cleanup."""

        self._automatic_thermal_loaded = False
        self._invalidate_automatic_thermal_context()

    def configure_automatic_filtration(self, *, enabled: bool) -> None:
        """Set the independent restart-reset filtration gate."""

        if self._automatic_filtration_gate_enabled == bool(enabled):
            return
        self._automatic_filtration_gate_enabled = bool(enabled)
        self._invalidate_automatic_filtration_context()

    def begin_automatic_filtration_epoch(self, epoch_identity: str) -> None:
        """Invalidate filtration commands bound to an older observation frame."""

        if not epoch_identity.strip():
            raise ValueError("automatic filtration epoch identity must not be empty")
        if epoch_identity == self._automatic_filtration_epoch_identity:
            return
        self._automatic_filtration_generation += 1
        self._automatic_filtration_epoch_identity = epoch_identity
        self._automatic_filtration_context = None

    def bind_automatic_filtration_dispatch(
        self,
        *,
        epoch_identity: str,
        session_identity: str,
        operation_identity: str,
        operation: str,
        target: str,
        requested_value: bool | int,
        pump_circuit_id: str,
        cleanup: bool = False,
        ownership_lease_id: str | None = None,
        body_activation_receipt_id: str | None = None,
        pump_session_id: str | None = None,
        effective_pump_rpm: int | None = None,
    ) -> AutomaticFiltrationDispatchContext:
        """Bind exactly one current canonical filtration operation."""

        if epoch_identity != self._automatic_filtration_epoch_identity:
            raise ValueError("automatic filtration epoch is not current")
        if operation == "pump_circuit_speed":
            expected = (
                self.baselines.filtration_rpm
                if effective_pump_rpm is None
                else effective_pump_rpm
            )
            if requested_value != expected:
                raise ValueError("operation exceeds exact automatic filtration envelope")
        context = AutomaticFiltrationDispatchContext(
            generation=self._automatic_filtration_generation,
            epoch_identity=epoch_identity,
            session_identity=session_identity,
            operation_identity=operation_identity,
            operation=operation,
            target=target,
            requested_value=requested_value,
            pump_circuit_id=pump_circuit_id,
            ownership_lease_id=ownership_lease_id,
            body_activation_receipt_id=body_activation_receipt_id,
            purpose=(
                AutomaticFiltrationDispatchPurpose.OWNED_BODY_CLEANUP
                if cleanup
                else AutomaticFiltrationDispatchPurpose.NORMAL
            ),
            policy_fingerprint=self.baselines.fingerprint,
            runtime_binding=self._runtime_binding,
            pump_session_id=pump_session_id,
            effective_pump_rpm=effective_pump_rpm,
        )
        self._automatic_filtration_context = context
        return context

    def unload_automatic_filtration_driver(self) -> None:
        """Make late filtration work inert without issuing cleanup."""

        self._automatic_filtration_loaded = False
        self._automatic_filtration_gate_enabled = False
        self._invalidate_automatic_filtration_context()

    def configure_grid_outage_safety(self, *, enabled: bool) -> None:
        """Set the independent default-off outage gate and invalidate old work."""

        if self._grid_outage_gate_enabled == bool(enabled):
            return
        self._grid_outage_gate_enabled = bool(enabled)
        self._invalidate_grid_outage_context()

    def begin_grid_outage_frame(
        self,
        *,
        outage_epoch_id: str | None,
        frame_identity: str,
    ) -> None:
        """Make every candidate from an older authoritative frame stale."""

        if not frame_identity.strip():
            raise ValueError("outage frame identity must not be empty")
        if (
            outage_epoch_id == self._grid_outage_epoch_id
            and frame_identity == self._grid_outage_frame_identity
        ):
            return
        self._grid_outage_generation += 1
        self._grid_outage_epoch_id = outage_epoch_id
        self._grid_outage_frame_identity = frame_identity
        self._grid_outage_authority = None
        self._invalidate_undispatched_grid_outage_expectations()

    def register_grid_outage_candidate(
        self,
        *,
        outage_epoch_id: str,
        frame_identity: str,
        candidate_id: str,
        purpose: GridOutageDispatchPurpose,
        operation: str,
        target: str,
        requested_value: bool | int | str,
    ) -> GridOutageDispatchAuthority:
        """Register one exact candidate in the current outage frame."""

        if (
            outage_epoch_id != self._grid_outage_epoch_id
            or frame_identity != self._grid_outage_frame_identity
        ):
            raise ValueError("grid outage candidate frame is not current")
        if (
            purpose is GridOutageDispatchPurpose.POOL_PUMP_REDUCTION
            and requested_value != self.baselines.grid_outage_rpm
        ):
            raise ValueError("outage authority does not match exact reduction envelope")
        authority = GridOutageDispatchAuthority(
            generation=self._grid_outage_generation,
            outage_epoch_id=outage_epoch_id,
            frame_identity=frame_identity,
            candidate_id=candidate_id,
            purpose=purpose,
            operation=operation,
            target=target,
            requested_value=requested_value,
            policy_fingerprint=self.baselines.fingerprint,
            runtime_binding=self._runtime_binding,
        )
        self._grid_outage_authority = authority
        return authority

    def bind_grid_outage_dispatch(
        self,
        authority: GridOutageDispatchAuthority,
    ) -> GridOutageDispatchContext:
        """Bind delivery to the exact currently registered outage candidate."""

        if authority != self._grid_outage_authority:
            raise ValueError("grid outage candidate is not current")
        return GridOutageDispatchContext(
            generation=authority.generation,
            outage_epoch_id=authority.outage_epoch_id,
            frame_identity=authority.frame_identity,
            candidate_id=authority.candidate_id,
            authority=authority,
        )

    def unload_grid_outage_safety(self) -> None:
        """Invalidate all outage authority without restoring equipment."""

        self._grid_outage_loaded = False
        self._grid_outage_gate_enabled = False
        self._invalidate_grid_outage_context()

    def _invalidate_grid_outage_context(self) -> None:
        self._grid_outage_generation += 1
        self._grid_outage_epoch_id = None
        self._grid_outage_frame_identity = None
        self._grid_outage_authority = None
        self._invalidate_undispatched_grid_outage_expectations()

    def _invalidate_undispatched_grid_outage_expectations(self) -> None:
        self._expectations = {
            key: item
            for key, item in self._expectations.items()
            if item.request.source is not PhysicalRequestSource.GRID_OUTAGE_SAFETY
            or item.dispatch_started
        }

    def _invalidate_automatic_thermal_context(self) -> None:
        self._automatic_thermal_generation += 1
        self._automatic_thermal_epoch_identity = None
        self._automatic_thermal_session_identity = None
        self._automatic_thermal_cleanup_authority = None
        self._automatic_thermal_probe_authority = None
        self._expectations = {
            key: item
            for key, item in self._expectations.items()
            if item.request.source is not PhysicalRequestSource.AUTOMATIC_THERMAL
        }

    def _invalidate_automatic_filtration_context(self) -> None:
        self._automatic_filtration_generation += 1
        self._automatic_filtration_epoch_identity = None
        self._automatic_filtration_context = None
        self._expectations = {
            key: item
            for key, item in self._expectations.items()
            if item.request.source is not PhysicalRequestSource.AUTOMATIC_FILTRATION
        }

    def assess(self, request: PhysicalCommandRequest) -> PhysicalAuthorityDecision:
        """Answer whether this request may physically dispatch right now."""

        reason = self.base_authority_reason
        if (
            reason is PhysicalAuthorityReason.ALLOWED
            and request.source
            in {
                PhysicalRequestSource.AUTOMATIC_THERMAL,
                PhysicalRequestSource.AUTOMATIC_FILTRATION,
                PhysicalRequestSource.GRID_OUTAGE_SAFETY,
            }
            and self._automatic_restoration_barrier_required
            and not (
                self._pool_automatic_restraint_restored
                and self._spa_automatic_restraint_restored
            )
        ):
            reason = PhysicalAuthorityReason.AUTOMATIC_RESTRAINT_RESTORATION_PENDING
        if (
            reason is PhysicalAuthorityReason.ALLOWED
            and self._pool_automatic_control_suppressed
            and _is_automatic_pool_request(request)
        ):
            reason = PhysicalAuthorityReason.POOL_AUTOMATIC_CONTROL_SUPPRESSED
        if (
            reason is PhysicalAuthorityReason.ALLOWED
            and self._spa_automatic_control_suppressed
            and _is_automatic_spa_request(request)
        ):
            reason = PhysicalAuthorityReason.SPA_AUTOMATIC_CONTROL_SUPPRESSED
        if (
            reason is PhysicalAuthorityReason.ALLOWED
            and request.source is PhysicalRequestSource.MANUAL
            and request.operation == "pump_circuit_speed"
            and request.manual_pump_session_id is not None
            and not self._manual_pump_session_request_current(request)
        ):
            reason = PhysicalAuthorityReason.MANUAL_PUMP_SESSION_STALE
        if (
            reason is PhysicalAuthorityReason.ALLOWED
            and request.source is PhysicalRequestSource.AUTOMATIC_THERMAL
        ):
            reason = self._automatic_thermal_reason(request)
        elif (
            reason is PhysicalAuthorityReason.ALLOWED
            and request.source is PhysicalRequestSource.AUTOMATIC_FILTRATION
        ):
            reason = self._automatic_filtration_reason(request)
        elif (
            reason is PhysicalAuthorityReason.ALLOWED
            and request.source is PhysicalRequestSource.GRID_OUTAGE_SAFETY
        ):
            reason = self._grid_outage_reason(request)
        return PhysicalAuthorityDecision(
            allowed=reason is PhysicalAuthorityReason.ALLOWED,
            reason=reason,
            request=request,
            maintenance_mode=self._maintenance_mode,
            controller_mode=self._controller_mode,
        )

    def _manual_pump_session_request_current(
        self,
        request: PhysicalCommandRequest,
    ) -> bool:
        binding = self._pump_session_binding
        return bool(
            binding is not None
            and request.manual_pump_session_id == binding[0]
            and request.target == binding[3]
            and type(request.requested_value) is int
            and request.requested_value == binding[4]
        )

    @property
    def base_authority_reason(self) -> PhysicalAuthorityReason:
        """Return current Maintenance/controller authority without a request."""

        if self._maintenance_mode is None:
            return PhysicalAuthorityReason.AUTHORITY_UNRESOLVED
        if self._maintenance_mode:
            return PhysicalAuthorityReason.MAINTENANCE_MODE
        if self._controller_mode is None:
            return PhysicalAuthorityReason.CONTROLLER_MODE_UNRESOLVED
        if self._controller_mode == "service":
            return PhysicalAuthorityReason.CONTROLLER_SERVICE_MODE
        if self._controller_mode == "timeout":
            return PhysicalAuthorityReason.CONTROLLER_TIMEOUT_MODE
        return PhysicalAuthorityReason.ALLOWED

    def _automatic_thermal_reason(
        self,
        request: PhysicalCommandRequest,
    ) -> PhysicalAuthorityReason:
        context = request.automatic_thermal_context
        if not self._automatic_thermal_loaded:
            return PhysicalAuthorityReason.AUTOMATIC_THERMAL_DRIVER_UNLOADED
        if not self._automatic_thermal_driver_enabled:
            return PhysicalAuthorityReason.AUTOMATIC_THERMAL_GATE_DISABLED
        if not self._automatic_thermal_live_enabled:
            return PhysicalAuthorityReason.THERMAL_LIVE_GATE_DISABLED
        if self._automatic_thermal_scope == "disabled":
            return PhysicalAuthorityReason.AUTOMATIC_THERMAL_SCOPE_DISABLED
        if context is None:
            return PhysicalAuthorityReason.AUTOMATIC_THERMAL_CONTEXT_MISSING
        if (
            context.runtime_binding
            and context.runtime_binding != self._runtime_binding
        ):
            return PhysicalAuthorityReason.AUTOMATIC_THERMAL_CONTEXT_STALE
        if context.policy_fingerprint != self.baselines.fingerprint:
            return PhysicalAuthorityReason.AUTOMATIC_THERMAL_CONTEXT_STALE
        if (
            request.operation == "pump_circuit_speed"
            and not self._pump_session_context_current(context)
        ):
            return PhysicalAuthorityReason.AUTOMATIC_THERMAL_CONTEXT_STALE
        if not _automatic_thermal_request_matches_context(
            request,
            context,
            self.baselines,
        ):
            return PhysicalAuthorityReason.AUTOMATIC_THERMAL_OPERATION_UNAUTHORIZED
        if self._automatic_thermal_scope != context.body:
            return PhysicalAuthorityReason.AUTOMATIC_THERMAL_SCOPE_MISMATCH
        if (
            context.generation != self._automatic_thermal_generation
            or context.epoch_identity != self._automatic_thermal_epoch_identity
            or context.session_identity != self._automatic_thermal_session_identity
        ):
            return PhysicalAuthorityReason.AUTOMATIC_THERMAL_CONTEXT_STALE
        if (
            context.purpose is AutomaticThermalDispatchPurpose.POOL_TEMPERATURE_PROBE
            and context.probe_authority != self._automatic_thermal_probe_authority
        ):
            return PhysicalAuthorityReason.AUTOMATIC_THERMAL_CONTEXT_STALE
        return PhysicalAuthorityReason.ALLOWED

    def _grid_outage_reason(
        self,
        request: PhysicalCommandRequest,
    ) -> PhysicalAuthorityReason:
        if not self._grid_outage_loaded:
            return PhysicalAuthorityReason.GRID_OUTAGE_DRIVER_UNLOADED
        if not self._grid_outage_gate_enabled:
            return PhysicalAuthorityReason.GRID_OUTAGE_GATE_DISABLED
        context = request.grid_outage_context
        if context is None:
            return PhysicalAuthorityReason.GRID_OUTAGE_CONTEXT_MISSING
        if context.authority != self._grid_outage_authority:
            return PhysicalAuthorityReason.GRID_OUTAGE_CONTEXT_STALE
        if (
            context.authority.runtime_binding
            and context.authority.runtime_binding != self._runtime_binding
        ):
            return PhysicalAuthorityReason.GRID_OUTAGE_CONTEXT_STALE
        if context.authority.policy_fingerprint != self.baselines.fingerprint:
            return PhysicalAuthorityReason.GRID_OUTAGE_CONTEXT_STALE
        if (
            context.generation != self._grid_outage_generation
            or context.outage_epoch_id != self._grid_outage_epoch_id
            or context.frame_identity != self._grid_outage_frame_identity
        ):
            return PhysicalAuthorityReason.GRID_OUTAGE_CONTEXT_STALE
        expected = context.authority
        if not (
            request.operation == expected.operation
            and request.target == expected.target
            and type(request.requested_value) is type(expected.requested_value)
            and request.requested_value == expected.requested_value
        ):
            return PhysicalAuthorityReason.GRID_OUTAGE_OPERATION_UNAUTHORIZED
        return PhysicalAuthorityReason.ALLOWED

    def _automatic_filtration_reason(
        self,
        request: PhysicalCommandRequest,
    ) -> PhysicalAuthorityReason:
        if not self._automatic_filtration_loaded:
            return PhysicalAuthorityReason.AUTOMATIC_FILTRATION_DRIVER_UNLOADED
        context = request.automatic_filtration_context
        if context is None:
            return PhysicalAuthorityReason.AUTOMATIC_FILTRATION_CONTEXT_MISSING
        if (
            context.runtime_binding
            and context.runtime_binding != self._runtime_binding
        ):
            return PhysicalAuthorityReason.AUTOMATIC_FILTRATION_CONTEXT_STALE
        if context.policy_fingerprint != self.baselines.fingerprint:
            return PhysicalAuthorityReason.AUTOMATIC_FILTRATION_CONTEXT_STALE
        if (
            request.operation == "pump_circuit_speed"
            and not self._pump_session_context_current(context)
        ):
            return PhysicalAuthorityReason.AUTOMATIC_FILTRATION_CONTEXT_STALE
        if context != self._automatic_filtration_context or (
            context.generation != self._automatic_filtration_generation
            or context.epoch_identity != self._automatic_filtration_epoch_identity
        ):
            return PhysicalAuthorityReason.AUTOMATIC_FILTRATION_CONTEXT_STALE
        if (
            not self._automatic_filtration_gate_enabled
            and context.purpose
            is not AutomaticFiltrationDispatchPurpose.OWNED_BODY_CLEANUP
        ):
            return PhysicalAuthorityReason.AUTOMATIC_FILTRATION_GATE_DISABLED
        if not _automatic_filtration_request_matches_context(request, context):
            return PhysicalAuthorityReason.AUTOMATIC_FILTRATION_OPERATION_UNAUTHORIZED
        return PhysicalAuthorityReason.ALLOWED

    def _pump_session_context_current(
        self,
        context: AutomaticThermalDispatchContext | AutomaticFiltrationDispatchContext,
    ) -> bool:
        if context.pump_session_id is None:
            # Backward-compatible default-baseline contexts remain exact and
            # restrictive; configured overrides require the stronger binding.
            return context.effective_pump_rpm is None
        purpose = (
            context.operating_purpose
            if isinstance(context, AutomaticThermalDispatchContext)
            else "ordinary_circulation"
        )
        return self._pump_session_binding == (
            context.pump_session_id,
            context.body if isinstance(context, AutomaticThermalDispatchContext) else "pool",
            purpose,
            context.pump_circuit_id,
            context.effective_pump_rpm,
        )

    def require_allowed(self, request: PhysicalCommandRequest) -> None:
        decision = self.assess(request)
        if not decision.allowed:
            raise PhysicalCommandDeniedError(decision)

    def reserve(
        self,
        request: PhysicalCommandRequest,
        consequence: ExpectedNativeConsequence,
        *,
        now: datetime,
    ) -> str | None:
        """Reserve a transition correlation unless native truth is already equal."""

        _require_aware(now)
        self.require_allowed(request)
        self.expire(now=now)
        current = self._native_truth.get(
            (consequence.concept, consequence.native_object_id)
        )
        if current is not None and _matches(consequence, current):
            return None
        if len(self._expectations) >= self.expectation_limit:
            raise RuntimeError("native consequence expectation capacity exhausted")
        expectation_id = str(uuid4())
        self._expectations[expectation_id] = _PendingExpectation(
            expectation_id=expectation_id,
            request=request,
            consequence=consequence,
            reserved_at=now,
            expires_at=now + self.expectation_ttl,
        )
        return expectation_id

    def mark_dispatch_started(self, expectation_id: str) -> None:
        self._expectations[expectation_id].dispatch_started = True

    def supersede_dispatched_expectations(self, request: PhysicalCommandRequest) -> None:
        """A new write retires older consequences of that same native operation."""

        self._expectations = {
            key: item
            for key, item in self._expectations.items()
            if not (
                item.dispatch_started
                and item.request.request_id != request.request_id
                and item.request.operation == request.operation
                and item.request.target == request.target
            )
        }

    def cancel(self, expectation_id: str) -> bool:
        return self._expectations.pop(expectation_id, None) is not None

    def invalidate_expectations(self) -> None:
        self._expectations.clear()

    def replace_native_truth(
        self,
        values: Mapping[tuple[str, str], Any],
    ) -> None:
        """Replace the bounded authoritative truth used only for no-op detection."""

        self._native_truth = {
            (str(concept), str(native_object_id)): value
            for (concept, native_object_id), value in values.items()
            if concept and native_object_id
        }

    def expire(self, *, now: datetime) -> int:
        _require_aware(now)
        expired = [
            key for key, item in self._expectations.items() if item.expires_at <= now
        ]
        for key in expired:
            self._expectations.pop(key, None)
        return len(expired)

    def correlate(
        self,
        *,
        concept: str,
        native_object_id: str | None,
        value: Any,
        observed_at: datetime,
    ) -> NativeConsequenceAttribution | None:
        """Attribute native truth; repeated analog matches retain the original expiry."""

        _require_aware(observed_at)
        self.expire(now=observed_at)
        candidates = sorted(
            self._expectations.values(), key=lambda item: (item.reserved_at, item.expectation_id)
        )
        for item in candidates:
            expected = item.consequence
            if not item.dispatch_started:
                continue
            if expected.concept != concept:
                continue
            if expected.native_object_id != native_object_id:
                continue
            if observed_at < item.reserved_at:
                continue
            if not _matches(expected, value):
                if expected.retain_matching_updates:
                    self._expectations.pop(item.expectation_id, None)
                continue
            if not expected.retain_matching_updates:
                self._expectations.pop(item.expectation_id, None)
            return NativeConsequenceAttribution(
                expectation_id=item.expectation_id,
                request_id=item.request.request_id,
                request_source=item.request.source,
                operation=item.request.operation,
                target=item.request.target,
            )
        return None

    def diagnostics(self, *, now: datetime) -> Mapping[str, Any]:
        self.expire(now=now)
        return MappingProxyType(
            {
                "maintenance_resolved": self.maintenance_resolved,
                "maintenance_mode": self._maintenance_mode,
                "controller_mode": self._controller_mode,
                "physical_commands_allowed": (
                    self._maintenance_mode is False and self._controller_mode == "auto"
                ),
                "pump_operating_baselines": dict(self.baselines.as_dict()),
                "pump_operating_baselines_fingerprint": self.baselines.fingerprint,
                "pool_automatic_control_suppressed": (
                    self._pool_automatic_control_suppressed
                ),
                "spa_automatic_control_suppressed": (
                    self._spa_automatic_control_suppressed
                ),
                "automatic_restoration_barrier_required": (
                    self._automatic_restoration_barrier_required
                ),
                "pool_automatic_restraint_restored": (
                    self._pool_automatic_restraint_restored
                ),
                "spa_automatic_restraint_restored": (
                    self._spa_automatic_restraint_restored
                ),
                "automatic_restoration_complete": (
                    not self._automatic_restoration_barrier_required
                    or (
                        self._pool_automatic_restraint_restored
                        and self._spa_automatic_restraint_restored
                    )
                ),
                "pending_expectation_count": len(self._expectations),
                "pending_expectation_limit": self.expectation_limit,
                "expectation_ttl_seconds": self.expectation_ttl.total_seconds(),
                "automatic_thermal_driver_enabled": (
                    self._automatic_thermal_driver_enabled
                ),
                "automatic_thermal_live_enabled": self._automatic_thermal_live_enabled,
                "automatic_thermal_scope": self._automatic_thermal_scope,
                "automatic_thermal_loaded": self._automatic_thermal_loaded,
                "automatic_thermal_generation": self._automatic_thermal_generation,
                "automatic_thermal_cleanup_candidate": (
                    None
                    if self._automatic_thermal_cleanup_authority is None
                    else self._automatic_thermal_cleanup_authority.candidate_identity
                ),
                "automatic_filtration_gate_enabled": (
                    self._automatic_filtration_gate_enabled
                ),
                "automatic_filtration_loaded": self._automatic_filtration_loaded,
                "automatic_filtration_generation": (
                    self._automatic_filtration_generation
                ),
                "grid_outage_safety_gate_enabled": self._grid_outage_gate_enabled,
                "grid_outage_safety_loaded": self._grid_outage_loaded,
                "grid_outage_generation": self._grid_outage_generation,
                "grid_outage_candidate": (
                    None
                    if self._grid_outage_authority is None
                    else self._grid_outage_authority.candidate_id
                ),
            }
        )


def _automatic_thermal_request_matches_context(
    request: PhysicalCommandRequest,
    context: AutomaticThermalDispatchContext,
    baselines: PumpOperatingBaselines,
) -> bool:
    body_target = "B1101" if context.body == "pool" else "B1202"
    if context.purpose is AutomaticThermalDispatchPurpose.POOL_TEMPERATURE_PROBE:
        probe = context.probe_authority
        return bool(
            probe is not None
            and request.operation == probe.operation
            and request.target == probe.target
            and type(request.requested_value) is type(probe.requested_value)
            and request.requested_value == probe.requested_value
            and (
                context.effective_pump_rpm is None
                or request.operation != "pump_circuit_speed"
                or request.requested_value == context.effective_pump_rpm
            )
        )
    if context.purpose is AutomaticThermalDispatchPurpose.TERMINATION:
        return (
            request.operation == "body_heat_source"
            and request.target == body_target
            and request.requested_value == "00000"
        )
    if context.purpose in {
        AutomaticThermalDispatchPurpose.CIRCULATION_BODY_CLEANUP,
        AutomaticThermalDispatchPurpose.CIRCULATION_PUMP_NORMALIZATION,
    }:
        cleanup = context.cleanup_authority
        return bool(
            cleanup is not None
            and request.operation == cleanup.operation
            and request.target == cleanup.target
            and request.requested_value == cleanup.requested_value
        )
    if request.operation == "body_active":
        return request.target == body_target and request.requested_value is True
    if request.operation == "body_heat_source":
        return (
            request.target == body_target
            and request.requested_value in {"00000", "H0001", "H0002"}
        )
    if request.operation == "pump_circuit_speed":
        session_rpm = context.effective_pump_rpm
        if context.body == "hot_tub":
            expected_hot_tub_rpm = session_rpm if session_rpm is not None else {
                "temperature_acquisition": baselines.temperature_probe_rpm,
                "ordinary_circulation": baselines.filtration_rpm,
                "solar_heating": baselines.solar_heating_rpm,
                "gas_heating": baselines.gas_heating_rpm,
            }.get(
                context.operating_purpose
                if context.operating_purpose is not None
                else ""
            )
            return bool(
                context.pump_circuit_id is not None
                and request.target == context.pump_circuit_id
                and type(request.requested_value) is int
                and request.requested_value == expected_hot_tub_rpm
            )
        expected_pool_rpm = session_rpm if session_rpm is not None else {
            None: baselines.priming_rpm,
            "priming": baselines.priming_rpm,
            "ordinary_circulation": baselines.filtration_rpm,
            "solar_heating": baselines.solar_heating_rpm,
            "gas_heating": baselines.gas_heating_rpm,
        }.get(context.operating_purpose)
        return bool(
            context.pump_circuit_id is not None
            and request.target == context.pump_circuit_id
            and type(request.requested_value) is int
            and request.requested_value == expected_pool_rpm
        )
    return False


def _is_automatic_pool_request(request: PhysicalCommandRequest) -> bool:
    """Identify Pool-scoped automatic work without affecting manual control."""

    if request.source is PhysicalRequestSource.AUTOMATIC_FILTRATION:
        return True
    if request.source is PhysicalRequestSource.AUTOMATIC_THERMAL:
        thermal_context = request.automatic_thermal_context
        return thermal_context is not None and thermal_context.body == "pool"
    if request.source is PhysicalRequestSource.GRID_OUTAGE_SAFETY:
        outage_context = request.grid_outage_context
        if outage_context is None:
            return request.target == "B1101"
        return outage_context.authority.purpose in {
            GridOutageDispatchPurpose.POOL_SOURCE_OFF,
            GridOutageDispatchPurpose.POOL_PUMP_REDUCTION,
        }
    return False


def _is_automatic_spa_request(request: PhysicalCommandRequest) -> bool:
    """Identify Spa-scoped automatic work without affecting Pool automation."""

    if request.source is not PhysicalRequestSource.AUTOMATIC_THERMAL:
        return False
    thermal_context = request.automatic_thermal_context
    return thermal_context is not None and thermal_context.body == "hot_tub"


def _automatic_filtration_request_matches_context(
    request: PhysicalCommandRequest,
    context: AutomaticFiltrationDispatchContext,
) -> bool:
    return bool(
        request.operation == context.operation
        and request.target == context.target
        and type(request.requested_value) is type(context.requested_value)
        and request.requested_value == context.requested_value
    )


def _matches(expected: ExpectedNativeConsequence, value: Any) -> bool:
    if expected.numeric_tolerance:
        if isinstance(value, bool) or isinstance(expected.expected_value, bool):
            return False
        try:
            return abs(float(value) - float(expected.expected_value)) <= expected.numeric_tolerance
        except (TypeError, ValueError):
            return False
    return value == expected.expected_value


def _grid_outage_shape_matches(
    operation: str,
    target: str,
    value: bool | int | str,
    shape: tuple[str, str, bool | int | str],
) -> bool:
    return (
        operation == shape[0]
        and target == shape[1]
        and type(value) is type(shape[2])
        and value == shape[2]
    )


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")


__all__ = [
    "AutomaticFiltrationDispatchContext",
    "AutomaticFiltrationDispatchPurpose",
    "AutomaticThermalCleanupAuthority",
    "AutomaticThermalProbeAuthority",
    "AutomaticThermalDispatchPurpose",
    "AutomaticThermalDispatchContext",
    "ExpectedNativeConsequence",
    "GridOutageDispatchAuthority",
    "GridOutageDispatchContext",
    "GridOutageDispatchPurpose",
    "NativeConsequenceAttribution",
    "PhysicalAuthorityDecision",
    "PhysicalAuthorityReason",
    "PhysicalCommandDeniedError",
    "PhysicalCommandRequest",
    "PhysicalRequestSource",
    "PoolOSPhysicalCommandAuthority",
]
