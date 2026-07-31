"""Permanent end-to-end golden scenarios for the supervisory runtime."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable


class GoldenScenarioStatus(str, Enum):
    """Outcome of one deterministic golden scenario."""

    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class GoldenScenario:
    """Named deterministic scenario and its verification callback."""

    scenario_id: str
    description: str
    verify: Callable[[], None]

    def __post_init__(self) -> None:
        if not self.scenario_id.strip():
            raise ValueError("scenario_id must not be empty")
        if not self.description.strip():
            raise ValueError("description must not be empty")


@dataclass(frozen=True, slots=True)
class GoldenScenarioResult:
    """Result of one scenario verification."""

    scenario_id: str
    status: GoldenScenarioStatus
    failure: str | None = None


@dataclass(frozen=True, slots=True)
class GoldenScenarioReport:
    """Immutable report for a complete golden-scenario suite."""

    results: tuple[GoldenScenarioResult, ...]

    @property
    def passed(self) -> bool:
        return all(result.status is GoldenScenarioStatus.PASSED for result in self.results)

    @property
    def passed_count(self) -> int:
        return sum(result.status is GoldenScenarioStatus.PASSED for result in self.results)

    @property
    def failed_count(self) -> int:
        return len(self.results) - self.passed_count


@dataclass(frozen=True, slots=True)
class GoldenScenarioSuite:
    """Run permanent deterministic scenarios in stable ID order."""

    scenarios: tuple[GoldenScenario, ...]

    def __post_init__(self) -> None:
        ids = tuple(scenario.scenario_id for scenario in self.scenarios)
        if len(ids) != len(set(ids)):
            raise ValueError("golden scenario IDs must be unique")

    def run(self) -> GoldenScenarioReport:
        results: list[GoldenScenarioResult] = []
        for scenario in sorted(self.scenarios, key=lambda item: item.scenario_id):
            try:
                scenario.verify()
            except Exception as exc:  # noqa: BLE001
                results.append(
                    GoldenScenarioResult(
                        scenario.scenario_id,
                        GoldenScenarioStatus.FAILED,
                        f"{type(exc).__name__}: {exc}",
                    )
                )
            else:
                results.append(
                    GoldenScenarioResult(
                        scenario.scenario_id,
                        GoldenScenarioStatus.PASSED,
                    )
                )
        return GoldenScenarioReport(tuple(results))
