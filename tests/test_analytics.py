from __future__ import annotations

import pandas as pd

from jarred_drive.analytics import (
    build_crash_dynamics,
    build_electrical_phase_summary,
    build_launch_attempts,
    build_launch_curves,
    build_rides,
    build_thermal_analysis,
    health_status,
    summarize_session,
    system_monitoring_summary,
)
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


def test_launch_diagnostics_separate_success_abort_and_launch_crash() -> None:
    _, telemetry, events, _, summary = _analyze(0)
    attempts = build_launch_attempts(telemetry, events)
    curves = build_launch_curves(telemetry, attempts)
    assert attempts["outcome"].value_counts().to_dict() == {
        "SUCCESS": 6,
        "LAUNCH_CRASH": 1,
        "FAILED": 1,
    }
    assert summary["failed_launch_rate"] == 0.25
    assert attempts["peak_power_W"].gt(0).all()
    assert attempts["voltage_sag_V"].gt(0).all()
    assert set(curves["attempt_id"].unique()) == set(attempts["attempt_id"])


def test_crash_dynamics_distinguish_launch_and_ride_falls() -> None:
    _, telemetry, events, _, _ = _analyze(0)
    crashes = build_crash_dynamics(telemetry, events)
    assert crashes["crash_type"].value_counts().to_dict() == {
        "RIDE_FALL": 6,
        "LAUNCH_CRASH": 1,
    }
    assert crashes["peak_accel_delta_g"].min() > 1.0
    assert crashes["peak_gyro_dps"].min() > 100.0


def test_thermal_analysis_finds_pack_four_anomaly_by_phase() -> None:
    _, telemetry, _, _, _ = _analyze(1)
    trace, sensors, phases = build_thermal_analysis(telemetry)
    hottest = sensors.sort_values("peak_C", ascending=False).iloc[0]
    assert hottest["sensor"] == "pack4_C"
    assert float(trace["pack_spread_C"].max()) > 7.0
    assert {"IDLE", "ACCELERATING", "FOILING", "TOUCHDOWN", "FALL"}.issubset(set(phases["phase"]))


def test_system_monitoring_surfaces_logger_and_gps_degradation() -> None:
    _, telemetry, _, _, _ = _analyze(1)
    monitor = system_monitoring_summary(telemetry)
    electrical = build_electrical_phase_summary(telemetry)
    assert 0.9 < monitor["gps_fix_fraction"] < 1.0
    assert 0.9 < monitor["sd_ok_fraction"] < 1.0
    assert monitor["sample_rate_hz"] == 10.0
    assert electrical["energy_Wh"].sum() > 0
    assert "ACCELERATING" in set(electrical["phase"])
