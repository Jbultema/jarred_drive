from __future__ import annotations

from pathlib import Path


def test_firmware_has_no_propulsion_or_configuration_write_calls() -> None:
    source = Path("firmware/src/main.cpp").read_text(encoding="utf-8")
    prohibited = (
        "setCurrent(",
        "setBrakeCurrent(",
        "setDuty(",
        "setRPM(",
        "setNunchuckValues(",
        "setMcconf",
        "COMM_SET_",
    )
    assert not [token for token in prohibited if token in source]
