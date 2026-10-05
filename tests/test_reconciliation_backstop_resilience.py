"""Production-shaped reconciliation backstop resilience regressions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from test_native_coordinator_refresh_coalescing import (
    _FakeHass,
    _load_coordinator_module,
)


@pytest.mark.parametrize("failure_mode", ["exception", "hang"])
def test_backstop_recovers_after_failed_pass(
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    async def scenario() -> None:
        module = _load_coordinator_module()
        monkeypatch.setattr(
            module,
            "OBSERVATION_UPDATE_INTERVAL",
            timedelta(milliseconds=5),
        )
        monkeypatch.setattr(module.LOGGER, "exception", lambda *args, **kwargs: None)

        class Harness(module.PoolOSCoordinator):
            def __init__(self) -> None:
                self.hass = _FakeHass()
                self._unloading = False
                self._post_start_active = True
                self._native_reconciliation_task = None
                self.calls = 0
                self.data = None
                self.block_forever = asyncio.Event()

            async def _async_update_data(self) -> object:
                self.calls += 1
                if self.calls == 2:
                    if failure_mode == "exception":
                        raise RuntimeError("synthetic reconciliation failure")
                    await self.block_forever.wait()
                return SimpleNamespace(generated_at=datetime.now(UTC))

            def async_set_updated_data(self, snapshot: object) -> None:
                self.data = snapshot

        coordinator = Harness()
        coordinator._async_start_native_reconciliation_backstop()
        try:
            for _ in range(250):
                await asyncio.sleep(0.001)
                if (
                    getattr(coordinator, "_native_reconciliation_failure_count", 0) >= 1
                    and getattr(coordinator, "_native_reconciliation_success_count", 0) >= 2
                ):
                    break

            assert coordinator.calls >= 3
            assert coordinator._native_reconciliation_failure_count == 1
            assert coordinator._native_reconciliation_success_count >= 2
            assert coordinator._native_reconciliation_task is not None
            assert not coordinator._native_reconciliation_task.done()
            assert coordinator._native_reconciliation_last_failure_at is not None
            reason = coordinator._native_reconciliation_last_failure_reason
            assert reason is not None
            if failure_mode == "exception":
                assert "RuntimeError: synthetic reconciliation failure" in reason
            else:
                assert "TimeoutError" in reason
        finally:
            coordinator._unloading = True
            coordinator._post_start_active = False
            task = coordinator._native_reconciliation_task
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_backstop_diagnostics_are_not_unconditionally_healthy() -> None:
    source = _load_coordinator_module().__file__
    assert source is not None
    text = open(source, encoding="utf-8").read()
    assert '"periodic_reconciliation_configured": True' in text
    assert '"periodic_reconciliation_task_running"' in text
    assert '"periodic_reconciliation_attempt_count"' in text
    assert '"periodic_reconciliation_success_count"' in text
    assert '"periodic_reconciliation_failure_count"' in text
    assert '"periodic_reconciliation_last_failure_reason"' in text
