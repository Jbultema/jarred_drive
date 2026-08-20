from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from jarred_drive.config import load_config
from jarred_drive.synthetic import SCENARIOS, generate_session, write_demo_package


def test_generation_is_deterministic() -> None:
    first = generate_session(SCENARIOS[0])
    second = generate_session(SCENARIOS[0])
    pd.testing.assert_frame_equal(first, second)


def test_demo_package_contains_commissioning_scenarios(tmp_path: Path) -> None:
    write_demo_package(tmp_path, load_config())
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert len(manifest["sessions"]) == 4
    device = json.loads((tmp_path / "device.json").read_text())
    assert device["data_kind"] == "synthetic"
    assert device["capabilities"]["config_write"] is False
    for scenario in SCENARIOS:
        assert (tmp_path / scenario.session_id / "telemetry.csv").exists()
        assert (tmp_path / scenario.session_id / "events.csv").exists()
        assert (tmp_path / scenario.session_id / "rides.csv").exists()
        assert (tmp_path / scenario.session_id / "launches.csv").exists()
        assert (tmp_path / scenario.session_id / "crashes.csv").exists()
        assert (tmp_path / scenario.session_id / "thermal_sensors.csv").exists()
        assert (tmp_path / scenario.session_id / "thermal_phases.csv").exists()
        assert (tmp_path / scenario.session_id / "electrical_phases.csv").exists()
        assert (tmp_path / scenario.session_id / "monitoring.json").exists()
        assert (tmp_path / scenario.session_id / "summary.json").exists()
        session_manifest = json.loads(
            (tmp_path / scenario.session_id / "manifest.json").read_text()
        )
        assert session_manifest["data_kind"] == "synthetic"
        assert session_manifest["scenario"] == scenario.name

    baseline = json.loads((tmp_path / "configs" / "FOIL_001.json").read_text())
    repeat = json.loads((tmp_path / "configs" / "FOIL_004.json").read_text())
    changed = {
        key
        for key in baseline.keys() | repeat.keys()
        if key not in {"config_id", "name", "synthetic_comparison_note"}
        and baseline.get(key) != repeat.get(key)
    }
    assert changed == {"throttle_ramp_seconds"}


def test_synthetic_motion_couples_turns_gps_and_imu() -> None:
    frame = generate_session(SCENARIOS[0])
    assert frame["gps_course_deg"].nunique() > 100
    assert frame["gps_lat"].max() - frame["gps_lat"].min() > 0.001
    assert frame["gps_lon"].max() - frame["gps_lon"].min() > 0.001
    assert frame.loc[frame["sim_state"] == "FOILING", "gps_speed_mps"].median() > 5.0
    assert frame.loc[frame["sim_state"] == "FALL", "gyro_z_dps"].abs().max() > 100.0
    assert {"SUCCESS", "FAILED", "LAUNCH_CRASH"}.issubset(set(frame["sim_outcome"]))
