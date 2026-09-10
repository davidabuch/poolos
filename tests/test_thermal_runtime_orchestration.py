

def test_integer_native_configured_pump_speed_accepts_integral_float() -> None:
    """Native IntelliCenter numeric RPM values may arrive as integral floats."""

    from poolos.thermal_runtime_orchestration import _integer

    assert _integer(1500.0) == 1500
    assert _integer(2900.0) == 2900
    assert _integer(1500) == 1500

    assert _integer(True) is None
    assert _integer(False) is None
    assert _integer(1500.5) is None
    assert _integer(-1.0) is None
