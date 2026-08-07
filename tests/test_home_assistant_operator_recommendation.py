"""Contract tests for read-only Home Assistant recommendation publication."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "poolos"


def test_sensor_exposes_operator_recommendation_read_only() -> None:
    source = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert '"operator_recommendation"' in source
    assert '"Operator Recommendation"' in source
    assert '"NOT_AVAILABLE"' in source
    assert "_recommendation_attributes" in source


def test_coordinator_stores_advisory_evidence_without_execution() -> None:
    source = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert "operator_recommendation: OperatorRecommendation | None = None" in source
    assert "publish_operator_recommendation" in source
    assert "async_call" not in source
    assert "services.async_call" not in source


def test_dashboard_displays_recommendation_and_advisory_warning() -> None:
    text = (ROOT / "dashboards" / "poolos_control_center.yaml").read_text(encoding="utf-8")
    assert "sensor.poolos_operator_recommendation" in text
    assert "advisory commissioning evidence only" in text
    assert "cannot actuate equipment" in text


def test_adr_and_roadmap_record_11_2d() -> None:
    assert (ROOT / "docs" / "adr" / "ADR-081-operator-recommendations.md").is_file()
    roadmap = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    assert "| 11.2D | Operator recommendations | DONE |" in roadmap
    assert "### Epic 11.2D — Operator Recommendations" in roadmap
