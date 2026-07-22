# Buch IntelliCenter API Contract

## Status

This document defines the proposed public contract for:

```text
Buch IntelliCenter API v1
```

The contract should be implemented incrementally. Read-only controller and body state will be implemented before hardware command methods.

---

# Purpose

The Buch IntelliCenter API provides a stable, typed interface between the live Pentair equipment model and higher-level Home Assistant software such as Pool Manager.

The API translates Pentair-specific objects, attributes, and command behavior into predictable pool-equipment concepts.

It does not make operational decisions.

---

# Architectural Position

```text
Pentair IntelliCenter
        |
        v
pyintellicenter
        |
        v
IntelliCenterCoordinator
        |
        +--> Home Assistant entities and services
        |
        +--> Buch IntelliCenter API
                    |
                    v
        Future Python-based consumers
        such as a Pool Manager integration
```

The coordinator remains responsible for:

- Connection management
- Reconnection
- Live-model synchronization
- Processing push updates
- Reporting newly discovered equipment

The API reads from the coordinator's authoritative live model and sends commands through the coordinator's controller.

Home Assistant entities remain supported and are not replaced by API version 1.

---

# Current Pool Manager Compatibility

The current Pool Manager implementation is built primarily from Home Assistant YAML automations, scripts, helpers, entities, and services.

YAML automations cannot directly import or call an internal Python `api.py` module.

Therefore:

- Existing Pool Manager logic will continue using Home Assistant entities and services.
- The Buch IntelliCenter API will initially provide a clean internal Python contract.
- Pool Manager may consume the API directly if it is later converted into a Home Assistant custom integration.
- The API must not require an immediate Pool Manager rewrite.

This staged approach allows Buch IntelliCenter to gain a stable internal interface without disrupting the production Pool Manager system.

---

# Core Principles

## Authoritative model

The API must derive equipment state from the coordinator's live Pentair model.

It must not read equipment state back from Home Assistant entity state.

Home Assistant entity state is a presentation layer and may be delayed, unavailable, renamed, disabled, or customized.

## Separation of concerns

The API may:

- Identify Pentair equipment
- Normalize Pentair attributes
- Report controller and equipment state
- Report equipment capabilities
- Execute supported equipment commands
- Translate command and connection errors
- Allow Python consumers to subscribe to equipment updates

The API may not:

- Select schedules
- Determine equipment ownership
- Decide when heating should run
- Calculate operational priorities
- Optimize electricity or gas use
- Determine whether a pool or spa is ready
- Track operational runtime for policy purposes
- Send user notifications
- Implement Pool Manager safety policy

## Stable public contract

Pentair object names, raw attribute constants, coordinator diff structures, and `pyintellicenter` command objects should remain internal implementation details whenever practical.

Consumers should use normalized immutable API models rather than directly depending on `PoolObject`.

## Explicit availability

The API must distinguish between:

- Connected and known
- Disconnected
- Unsupported
- Unknown or not yet populated
- Equipment that no longer exists

Unavailable or unknown information must not silently become a normal value such as `0`, `False`, or an empty string.

## Capability-driven behavior

The API must report what each body or equipment item actually supports.

Consumers must not assume that:

- Every body supports cooling
- Every body has a heater
- Every body supports the same heat modes
- Every heater supports the same operation modes
- Every pump can be switched directly
- Every circuit is a light
- Every Pentair configuration uses the same equipment relationships

---

# Initial Scope

API version 1 will initially expose read-only information for:

- Controller connection state
- Controller identity
- Controller software version
- Pool and spa bodies
- Current water temperature
- Heating setpoint
- Cooling setpoint when supported
- Body enabled state
- Normalized HVAC mode and action
- Selected heater
- Heaters associated with each body
- Available heater or operation selections
- Circuits
- Lighting circuits
- Pumps
- Heaters
- Equipment capabilities
- Update subscriptions

Command methods will be added only after the corresponding read models and capability checks are tested.

Chemistry, schedules, covers, advanced pump programming, and controller configuration may be added later without breaking the initial interface.

---

# Identifier Rules

API identifiers must be stable across Home Assistant restarts.

Where practical, identifiers should be based on the Pentair object's stable object name, such as `OBJNAM`.

API identifiers must not depend on:

- Home Assistant entity IDs
- User-visible equipment names
- Entity registry names
- Platform-specific unique-ID suffixes

The API may expose user-visible names separately from stable identifiers.

Changing identifier behavior is a breaking API change unless a documented migration path is provided.

---

# Public Enumerations

Public normalized values should use string-backed enums.

An implementation may use definitions similar to:

```python
from enum import StrEnum


class AvailabilityState(StrEnum):
    AVAILABLE = "available"
    DISCONNECTED = "disconnected"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"


class BodyKind(StrEnum):
    POOL = "pool"
    SPA = "spa"
    UNKNOWN = "unknown"


class BodyHVACMode(StrEnum):
    OFF = "off"
    HEAT = "heat"
    HEAT_COOL = "heat_cool"
    UNKNOWN = "unknown"


class BodyHVACAction(StrEnum):
    OFF = "off"
    IDLE = "idle"
    HEATING = "heating"
    COOLING = "cooling"
    UNKNOWN = "unknown"
```

API version 1 should not advertise a generic `cool`-only HVAC mode unless the installed equipment and underlying command path genuinely support it.

The current cooling-capable climate entity exposes `off` and `heat_cool`.

---

# Public Models

Public models should be immutable snapshots.

## ControllerStatus

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ControllerStatus:
    connected: bool
    property_name: str | None
    software_version: str | None
```

## BodyCapabilities

```python
@dataclass(frozen=True, slots=True)
class BodyCapabilities:
    can_enable: bool
    can_set_heating_temperature: bool
    can_set_cooling_temperature: bool
    can_select_heater: bool
    can_select_operation_mode: bool
    supports_heating: bool
    supports_cooling: bool
```

## BodyState

```python
@dataclass(frozen=True, slots=True)
class BodyState:
    id: str
    name: str
    kind: BodyKind
    availability: AvailabilityState
    enabled: bool | None
    current_temperature: float | None
    heating_setpoint: float | None
    cooling_setpoint: float | None
    hvac_mode: BodyHVACMode
    hvac_action: BodyHVACAction
    selected_heater_id: str | None
    heater_ids: tuple[str, ...]
    operation_mode: str | None
    available_operation_modes: tuple[str, ...]
    capabilities: BodyCapabilities
```

`enabled` represents the Pentair Pool/Spa body status.

It does not mean that a heater is currently firing.

`hvac_action` represents current activity and should be normalized as:

```text
off
idle
heating
cooling
unknown
```

## EquipmentCapabilities

```python
@dataclass(frozen=True, slots=True)
class EquipmentCapabilities:
    can_enable: bool
```

## EquipmentState

```python
@dataclass(frozen=True, slots=True)
class EquipmentState:
    id: str
    name: str
    equipment_type: str
    availability: AvailabilityState
    is_on: bool | None
    capabilities: EquipmentCapabilities
```

Specialized models may later be introduced for:

- Heaters
- Pumps
- Lights
- Chemistry controllers
- Covers

A specialized model should be added when generic equipment fields would hide meaningful behavior or capabilities.

---

# Read Interface

The initial read-only API should support:

```python
api.controller_status()

api.bodies()
api.body(body_id)

api.circuits()
api.circuit(circuit_id)

api.lights()
api.light(light_id)

api.pumps()
api.pump(pump_id)

api.heaters()
api.heater(heater_id)
```

Collection methods return immutable tuples.

Lookup methods return `None` when the identifier does not correspond to known equipment.

A lookup returning `None` means that the equipment identifier is not present in the current model.

It is distinct from a known item whose availability is `disconnected` or `unknown`.

---

# Temperature Semantics

Heating and cooling targets are separate concepts.

For heating-only bodies:

```python
await api.async_set_body_heating_setpoint(body_id, temperature)
```

changes the Pentair heating setpoint.

For cooling-capable bodies:

```python
await api.async_set_body_heating_setpoint(body_id, temperature)

await api.async_set_body_cooling_setpoint(body_id, temperature)
```

change the low and high targets independently.

Setting a temperature:

- Does not automatically enable the Pool/Spa body
- Does not automatically select a heater
- Does not automatically change the heater operation mode
- Does not prove that the heater has started
- Does not mean that the requested temperature has been reached

Temperatures must be validated against the active IntelliCenter unit system and supported body limits.

The current integration uses:

```text
Imperial: 40–104 °F
Metric:    5–40 °C
```

The API implementation should use the integration's existing shared temperature-limit logic rather than duplicating these limits.

---

# Proposed Body Command Interface

The following methods describe the intended command contract:

```python
await api.async_set_body_enabled(body_id, enabled)

await api.async_set_body_heating_setpoint(
    body_id,
    temperature,
)

await api.async_set_body_cooling_setpoint(
    body_id,
    temperature,
)

await api.async_select_body_heater(
    body_id,
    heater_id,
)

await api.async_set_body_operation_mode(
    body_id,
    operation_mode,
)
```

Each method must perform capability validation before sending a command.

## Body enable behavior

Enabling a heating-only body should follow the behavior already implemented by `PoolHeatOnlyClimate`:

- Preserve a valid selected heater
- Select the first associated heater if no valid heater is selected
- Enable the Pool/Spa body

Disabling the body should:

- Turn off the Pool/Spa body
- Preserve its setpoint
- Preserve its heater selection for the next start

For a cooling-capable body, enabling should use the supported `heat_cool` behavior already implemented by the climate platform.

## Heater selection

Heater selection should use stable heater identifiers.

User-visible heater names may be exposed for display but must not be the primary command identifier.

The implementation must verify that the selected heater is associated with the requested body.

## Operation modes

Advanced combination heaters may expose equipment-specific operation labels such as gas, heat pump, hybrid, or dual modes.

The exact available labels come from the installed equipment configuration.

Consumers must obtain supported values from:

```python
body.available_operation_modes
```

or an equivalent capability method before attempting to set one.

Consumers must not assume that every body exposes advanced operation modes.

The API should treat operation-mode labels as opaque supported values unless a future normalized enum can represent them without losing hardware meaning.

---

# Proposed Circuit and Light Commands

The initial explicit equipment commands should be:

```python
await api.async_set_circuit_enabled(
    circuit_id,
    enabled,
)

await api.async_set_light_enabled(
    light_id,
    enabled,
)
```

Light-specific functionality such as color, effect, or light-show selection should use separate capability-driven methods when implemented.

The public API should not initially expose a single generic method such as:

```python
async_set_equipment_enabled(...)
```

because that would hide meaningful differences among bodies, circuits, lights, pumps, heaters, and configuration objects.

A generic private helper may still be used internally.

---

# Pump Commands

API version 1 may report detected pump state and capabilities.

It must not promise a universal method such as:

```python
await api.async_set_pump_enabled(pump_id, enabled)
```

until the supported Pentair pump-control paths are verified.

In many IntelliCenter configurations, pump operation is driven by body or circuit activation rather than by directly switching the pump object.

Advanced pump programming, speed control, flow control, and circuit assignments are outside the initial command scope.

---

# Command Requirements

Every command method must:

1. Verify that the controller is connected.
2. Validate that the target identifier exists.
3. Validate the target equipment type.
4. Validate that the equipment supports the requested operation.
5. Validate the requested value.
6. Use the established coordinator/controller command path.
7. Await the controller request when confirmation of command submission matters.
8. Translate underlying library exceptions into documented API exceptions.
9. Avoid reporting success solely from optimistic UI state.
10. Allow the authoritative Pentair push update to determine final equipment state.

A successfully awaited command means that the command was submitted without a reported controller or transport error.

It does not necessarily mean that:

- The physical equipment completed the requested transition
- A heater ignited
- A valve finished moving
- A pump reached speed
- The requested temperature was achieved

---

# Update Subscriptions

Python consumers should be able to subscribe without registering directly against the coordinator:

```python
remove_listener = api.async_add_listener(callback)
```

The callback should receive a normalized immutable update notice:

```python
@dataclass(frozen=True, slots=True)
class IntelliCenterUpdate:
    connected: bool
    connection_changed: bool
    full_refresh: bool
    changed_object_ids: frozenset[str]
```

`changed_object_ids` contains stable Pentair object identifiers affected by the update.

`full_refresh` should be `True` when consumers should reevaluate all relevant state.

A connection event may result in:

- `connection_changed=True`
- `full_refresh=True`
- An empty `changed_object_ids`

The subscription method returns a callable that removes the listener.

Listeners must run on the Home Assistant event loop and must not block it.

---

# Error Contract

The API should define a small exception hierarchy:

```python
class IntelliCenterAPIError(Exception):
    """Base Buch IntelliCenter API error."""


class EquipmentNotFoundError(IntelliCenterAPIError):
    """Requested equipment does not exist."""


class EquipmentTypeError(IntelliCenterAPIError):
    """Requested identifier refers to the wrong equipment type."""


class UnsupportedOperationError(IntelliCenterAPIError):
    """Equipment does not support the requested operation."""


class InvalidValueError(IntelliCenterAPIError):
    """Requested command value is invalid."""


class ControllerUnavailableError(IntelliCenterAPIError):
    """The IntelliCenter controller is unavailable."""


class CommandFailedError(IntelliCenterAPIError):
    """The controller rejected or failed the command."""
```

Consumers must not need to understand:

- `pyintellicenter` exception classes
- Home Assistant platform exceptions
- Raw transport exceptions
- Pentair command objects

Underlying exceptions should be preserved as exception causes for diagnostics.

---

# Home Assistant Boundary

The internal Python API is not a network-accessible external API.

API version 1 will not create:

- An HTTP endpoint
- A WebSocket endpoint
- An MQTT protocol
- A remote authentication mechanism
- A separate process

Home Assistant entities and services remain the supported interface for YAML automations.

If selected API capabilities later need to be exposed to YAML, they should be provided through documented Home Assistant services or entities that delegate to the same underlying implementation.

The internal API and Home Assistant platforms should share normalization and command helpers where practical so their behavior does not drift.

---

# Compatibility Rules

The following are public compatibility contracts:

- API class names
- Public method names
- Public data-model field names
- Normalized enum values
- Exception types
- Identifier behavior
- Command semantics
- Listener callback behavior
- Availability semantics

The following remain internal implementation details:

- `PoolObject`
- Raw Pentair attribute constants
- `pyintellicenter` command objects
- Coordinator update-diff structures
- Home Assistant entity IDs
- Entity unique-ID construction
- Platform implementation modules
- Private normalization helpers

Breaking a public contract requires:

1. A documented reason
2. A migration plan
3. A major API version change

Adding a new optional capability, model, field with a safe default, or method may remain within API version 1 when existing consumers continue to work unchanged.

---

# Versioning

The first implementation will be identified as:

```text
Buch IntelliCenter API v1
```

The Python module should expose:

```python
API_VERSION = 1
```

The API version is separate from the Buch IntelliCenter integration release version.

For example:

```text
Integration release: v3.8.1-buch.2
Internal API version: 1
```

Removing, renaming, or changing the meaning of a public field, enum value, identifier, listener event, or method requires a new major API version.

---

# Implementation Sequence

API version 1 should be implemented in the following order:

1. Controller status model
2. Body capability and state models
3. Read-only body lookup and enumeration
4. Unit tests for normalization and unavailable values
5. Update subscriptions
6. Read-only circuits, lights, heaters, and pumps
7. Body command methods
8. Circuit and light command methods
9. Shared helpers used by both the API and HA platforms
10. Optional Home Assistant services for capabilities needed by YAML consumers

No production entity should be migrated to depend on the API until the corresponding API behavior is tested.

---

# Non-Goals

API version 1 will not:

- Replace Home Assistant entities
- Require an immediate Pool Manager rewrite
- Move Pool Manager into Buch IntelliCenter
- Implement Pool Manager scheduling
- Implement equipment ownership
- Determine pool or spa readiness
- Perform runtime accounting for operational policy
- Implement energy optimization
- Expose every raw Pentair attribute
- Promise universal direct pump control
- Create a remote or network-accessible API
- Modify coordinator connection or reconnection behavior
- Report command success based only on optimistic state
- Treat heater selection as proof that heating is active
