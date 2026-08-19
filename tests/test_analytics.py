from __future__ import annotations

import pandas as pd

from jarred_drive.analytics import build_rides, health_status, summarize_session
from jarred_drive.config import load_config
from jarred_drive.events import detect_events
from jarred_drive.synthetic import SCENARIOS, generate_session


def _analyze(index: int):  # type: ignore[no-untyped-def]
    frame = generate_session(SCENARIOS[index])
    config = load_config()
    telemetry, events = detect_events(frame, config.detection, use_synthetic_truth=True)
    rides = build_rides(telemetry, events)
    return config, telemetry, events, rides, summarize_session(telemetry, events, rides)


def test_session_summary_has_physical_metrics() -> None:
    _, _, _, rides, summary = _analyze(0)
    assert len(rides) > 0
    assert summary["energy_Wh"] > 0
    assert summary["distance_m"] > 0
    assert 0 < summary["launch_success"] <= 1
    assert summary["longest_ride_seconds"] > 0


def test_nominal_session_is_ready() -> None:
    config, telemetry, _, _, _ = _analyze(0)
    assert health_status(telemetry, config.safety).level == "READY"


def test_thermal_anomaly_warns() -> None:
    config, telemetry, _, _, _ = _analyze(1)
    status = health_status(telemetry, config.safety)
    assert status.level in {"WARNING", "STOP"}
    assert any("Pack" in reason for reason in status.reasons)


def test_ingress_drill_stops_system() -> None:
    config, telemetry, _, _, _ = _analyze(2)
    status = health_status(telemetry, config.safety)
    assert status.level == "STOP"
    assert "Water ingress alarm latched" in status.reasons


def test_unknown_remote_status_is_not_reported_ready() -> None:
    config, telemetry, _, _, _ = _analyze(0)
    telemetry["remote_ok"] = telemetry["remote_ok"].astype("boolean")
    telemetry.loc[telemetry.index[-1], "remote_ok"] = pd.NA
    status = health_status(telemetry, config.safety)
    assert status.level == "WARNING"
    assert "Remote status unavailable in passive UART telemetry" in status.reasons
