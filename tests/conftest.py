"""Lightweight fixtures for testing the IntelliCenter read model.

These tests intentionally avoid starting Home Assistant. Minimal module stubs are
installed before the API modules are imported so the normalization logic can be
unit-tested in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_ROOT = ROOT / "intellicenter"
API_ROOT = INTEGRATION_ROOT / "api"


class UnitOfTemperature(StrEnum):
    CELSIUS = "°C"
    FAHRENHEIT = "°F"


class FakePoolObject:
    """Small stand-in for pyintellicenter.PoolObject."""

    def __init__(
        self,
        objnam: str,
        *,
        objtype: str = "BODY",
        sname: str | None = None,
        subtype: str | None = None,
        attrs: dict[str, Any] | None = None,
    ) -> None:
        self.objnam = objnam
        self.objtype = objtype
        self.sname = sname
        self.subtype = subtype
        self._attrs = dict(attrs or {})

    def __getitem__(self, key: str) -> Any:
        return self._attrs.get(key)

    @property
    def attribute_keys(self) -> set[str]:
        return set(self._attrs)


class FakeModel:
    def __init__(self, objects: list[FakePoolObject]) -> None:
        self._objects = list(objects)
        self._by_name = {obj.objnam: obj for obj in objects}

    def __getitem__(self, objnam: str) -> FakePoolObject | None:
        return self._by_name.get(objnam)

    def __iter__(self):
        return iter(self._objects)

    def get_by_type(self, objtype: str) -> list[FakePoolObject]:
        return [obj for obj in self._objects if obj.objtype == objtype]


class FakeController:
    def __init__(self) -> None:
        self.cooling_supported: set[str] = set()
        self.heating: set[str] = set()
        self.cooling: set[str] = set()

    def body_supports_cooling(self, body_objnam: str) -> bool:
        return body_objnam in self.cooling_supported

    def is_body_heating(self, body_objnam: str) -> bool:
        return body_objnam in self.heating

    def is_body_cooling(self, body_objnam: str) -> bool:
        return body_objnam in self.cooling


@dataclass
class FakeSystemInfo:
    uses_metric: bool = False
    prop_name: str = "Test IntelliCenter"
    sw_version: str = "9.9.9"


class FakeCoordinator:
    def __init__(
        self,
        objects: list[FakePoolObject],
        *,
        connected: bool = True,
        system_info: FakeSystemInfo | None = None,
    ) -> None:
        self.model = FakeModel(objects)
        self.controller = FakeController()
        self.connected = connected
        self.system_info = system_info or FakeSystemInfo()
        self.heaters_by_body: dict[str, tuple[str, ...]] = {}


def _install_stub_modules() -> None:
    homeassistant = ModuleType("homeassistant")
    homeassistant.__path__ = []
    ha_const = ModuleType("homeassistant.const")
    ha_const.UnitOfTemperature = UnitOfTemperature
    homeassistant.const = ha_const
    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.const"] = ha_const

    pyic = ModuleType("pyintellicenter")
    constants = {
        "BODY_TYPE": "BODY",
        "CIRCUIT_TYPE": "CIRCUIT",
        "FEATR_ATTR": "FEATR",
        "FREEZE_ATTR": "FREEZE",
        "HEATER_ATTR": "HEATER",
        "HITMP_ATTR": "HITMP",
        "HTMODE_ATTR": "HTMODE",
        "LOTMP_ATTR": "LOTMP",
        "LSTTMP_ATTR": "LSTTMP",
        "NULL_OBJNAM": "00000",
        "STATUS_ATTR": "STATUS",
        "STATUS_OFF": "OFF",
        "TIME_ATTR": "TIME",
        "USE_ATTR": "USE",
    }
    for name, value in constants.items():
        setattr(pyic, name, value)
    pyic.PoolObject = FakePoolObject
    sys.modules["pyintellicenter"] = pyic

    package = ModuleType("intellicenter")
    package.__path__ = [str(INTEGRATION_ROOT)]
    sys.modules["intellicenter"] = package

    api_package = ModuleType("intellicenter.api")
    api_package.__path__ = [str(API_ROOT)]
    sys.modules["intellicenter.api"] = api_package

    coordinator_module = ModuleType("intellicenter.coordinator")
    coordinator_module.IntelliCenterCoordinator = FakeCoordinator
    sys.modules["intellicenter.coordinator"] = coordinator_module

    def heaters_for_body(coordinator: FakeCoordinator, body_objnam: str):
        return coordinator.heaters_by_body.get(body_objnam, ())

    package.heaters_for_body = heaters_for_body


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_install_stub_modules()
MODELS = _load_module("intellicenter.api.models", API_ROOT / "models.py")
BODY = _load_module("intellicenter.api.body", API_ROOT / "body.py")
CIRCUIT = _load_module("intellicenter.api.circuit", API_ROOT / "circuit.py")
SYSTEM = _load_module("intellicenter.api.system", API_ROOT / "system.py")


@pytest.fixture
def api_modules() -> SimpleNamespace:
    return SimpleNamespace(
        models=MODELS, body=BODY, circuit=CIRCUIT, system=SYSTEM
    )


@pytest.fixture
def pool_object_factory():
    def factory(
        objnam: str = "B1101",
        *,
        name: str = "Pool",
        subtype: str = "POOL",
        status: str = "ON",
        current: Any = 86,
        target: Any = 90,
        cooling_target: Any = 95,
        heater: Any = "H0001",
        htmode: Any = "1",
    ) -> FakePoolObject:
        return FakePoolObject(
            objnam,
            objtype="BODY",
            sname=name,
            subtype=subtype,
            attrs={
                "STATUS": status,
                "LSTTMP": current,
                "LOTMP": target,
                "HITMP": cooling_target,
                "HEATER": heater,
                "HTMODE": htmode,
            },
        )

    return factory


@pytest.fixture
def heater_object_factory():
    def factory(
        objnam: str = "H0001",
        *,
        name: str = "MasterTemp Gas Heater",
        subtype: str = "GAS",
    ) -> FakePoolObject:
        return FakePoolObject(
            objnam,
            objtype="HEATER",
            sname=name,
            subtype=subtype,
        )

    return factory


@pytest.fixture
def coordinator_factory():
    def factory(
        objects: list[FakePoolObject],
        *,
        connected: bool = True,
        metric: bool = False,
    ) -> FakeCoordinator:
        return FakeCoordinator(
            objects,
            connected=connected,
            system_info=FakeSystemInfo(uses_metric=metric),
        )

    return factory


@pytest.fixture
def circuit_object_factory():
    def factory(
        objnam: str = "C0001",
        *,
        name: str = "Waterfall",
        subtype: str = "GENERIC",
        status: Any = "ON",
        use: Any = "FEATURE",
        feature: Any = "1",
        freeze: Any = "0",
        egg_timer: Any = 30,
    ) -> FakePoolObject:
        return FakePoolObject(
            objnam,
            objtype="CIRCUIT",
            sname=name,
            subtype=subtype,
            attrs={
                "STATUS": status,
                "USE": use,
                "FEATR": feature,
                "FREEZE": freeze,
                "TIME": egg_timer,
            },
        )

    return factory
