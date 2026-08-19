from __future__ import annotations

from jarred_drive.config import load_config
from jarred_drive.events import detect_events
from jarred_drive.schema import EventType
from jarred_drive.synthetic import SCENARIOS, generate_session


def test_truth_detector_finds_launches_and_falls() -> None:
    scenario = SCENARIOS[0]
    frame = generate_session(scenario)
    telemetry, events = detect_events(frame, load_config().detection, use_synthetic_truth=True)
    assert "battery_power_W" in telemetry
    assert (events["event_type"] == EventType.TAKEOFF).sum() == scenario.ride_count - 1
    assert (events["event_type"] == EventType.FALL).sum() == scenario.ride_count


def test_ingress_event_is_latched_once() -> None:
    frame = generate_session(SCENARIOS[2])
    _, events = detect_events(frame, load_config().detection, use_synthetic_truth=True)
    assert (events["event_type"] == EventType.WATER_DETECTED).sum() == 1


def test_pack_anomaly_emits_temperature_warning() -> None:
    frame = generate_session(SCENARIOS[1])
    _, events = detect_events(frame, load_config().detection, use_synthetic_truth=True)
    assert (events["event_type"] == EventType.TEMP_WARNING).sum() == 1


def test_baseline_detector_does_not_require_synthetic_truth() -> None:
    frame = generate_session(SCENARIOS[0]).drop(columns=["sim_state"])
    telemetry, events = detect_events(frame, load_config().detection)
    assert telemetry["state_inferred"].notna().all()
    assert not events.empty


def test_baseline_detector_can_operate_without_gps() -> None:
    gps_columns = [
        "gps_lat",
        "gps_lon",
        "gps_speed_mps",
        "gps_course_deg",
        "gps_fix_quality",
        "sim_state",
    ]
    frame = generate_session(SCENARIOS[0]).drop(columns=gps_columns)
    telemetry, events = detect_events(frame, load_config().detection)
    assert telemetry["state_inferred"].notna().all()
    assert (events["event_type"] == EventType.TAKEOFF).sum() > 0
