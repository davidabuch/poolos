"""Map Pentair command requests to concrete Home Assistant service calls."""

from __future__ import annotations

from dataclasses import dataclass

from poolos.delivery import PentairCommandRequest
from poolos.integration.pentair import PentairCommandOperation, PentairCommandParameter

from .models import HomeAssistantServiceCall
from .profile import HomeAssistantBindingProfile, PoolInstallationProfile


class HomeAssistantMappingError(ValueError):
    """Raised when a command cannot be mapped safely to Home Assistant."""


@dataclass(frozen=True, slots=True)
class PentairHomeAssistantCommandMapper:
    """Installation-aware mapper for logical Pentair command requests."""

    installation: PoolInstallationProfile
    bindings: HomeAssistantBindingProfile

    def map_command(self, request: PentairCommandRequest) -> HomeAssistantServiceCall:
        try:
            operation = PentairCommandOperation(request.operation)
        except ValueError as exc:
            raise HomeAssistantMappingError(
                f"unsupported Pentair operation {request.operation!r}"
            ) from exc

        context = {"correlation_id": request.correlation_id}
        if operation is PentairCommandOperation.SET_PUMP_SPEED:
            pump, binding = self._pump(request.target)
            rpm = request.parameters.get(PentairCommandParameter.RPM)
            if not isinstance(rpm, int) or isinstance(rpm, bool):
                raise HomeAssistantMappingError("pump.set_speed requires integer parameter 'rpm'")
            if not pump.minimum_rpm <= rpm <= pump.maximum_rpm:
                raise HomeAssistantMappingError(
                    f"rpm {rpm} is outside configured range "
                    f"{pump.minimum_rpm}-{pump.maximum_rpm} for {request.target}"
                )
            return HomeAssistantServiceCall(
                domain=binding.speed_command_entity.split(".", 1)[0],
                service="set_value",
                target={"entity_id": binding.speed_command_entity},
                data={"value": rpm},
                context=context,
            )

        if operation in {PentairCommandOperation.START_PUMP, PentairCommandOperation.STOP_PUMP}:
            _, binding = self._pump(request.target)
            return HomeAssistantServiceCall(
                domain="switch",
                service="turn_on" if operation is PentairCommandOperation.START_PUMP else "turn_off",
                target={"entity_id": binding.running_entity},
                context=context,
            )

        if operation is PentairCommandOperation.SET_HYDRAULIC_ROUTE:
            try:
                binding = self.bindings.hydraulic_routes[request.target]
            except KeyError as exc:
                raise HomeAssistantMappingError(
                    f"no hydraulic route binding configured for {request.target!r}"
                ) from exc
            suction = request.parameters.get(PentairCommandParameter.SUCTION_BODY_ID)
            return_body = request.parameters.get(PentairCommandParameter.RETURN_BODY_ID)
            if not isinstance(suction, str) or not isinstance(return_body, str):
                raise HomeAssistantMappingError(
                    "hydraulics.set_route requires suction_body_id and return_body_id"
                )
            route_key = f"{suction}:{return_body}"
            try:
                option = binding.options[route_key]
            except KeyError as exc:
                raise HomeAssistantMappingError(
                    f"no Home Assistant option configured for hydraulic route {route_key!r}"
                ) from exc
            return HomeAssistantServiceCall(
                domain=binding.route_entity.split(".", 1)[0],
                service="select_option",
                target={"entity_id": binding.route_entity},
                data={"option": option},
                context=context,
            )

        raise HomeAssistantMappingError(f"unsupported Pentair operation {request.operation!r}")

    def _pump(self, equipment_id: str):
        try:
            pump = self.installation.pumps[equipment_id]
        except KeyError as exc:
            raise HomeAssistantMappingError(f"unknown pump {equipment_id!r}") from exc
        try:
            binding = self.bindings.pumps[equipment_id]
        except KeyError as exc:
            raise HomeAssistantMappingError(
                f"no Home Assistant pump binding configured for {equipment_id!r}"
            ) from exc
        return pump, binding
