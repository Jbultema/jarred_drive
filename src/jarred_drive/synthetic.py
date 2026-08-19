"""Deterministic synthetic sessions for development before hardware exists."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from jarred_drive.analytics import build_rides, summarize_session
from jarred_drive.config import AppConfig
from jarred_drive.events import detect_events
from jarred_drive.schema import SCHEMA_VERSION, RideState


@dataclass(frozen=True)
class Scenario:
    session_id: str
    config_id: str
    name: str
    seed: int
    ride_count: int
    thermal_anomaly: bool = False
    water_ingress: bool = False
    vesc_fault: bool = False


SCENARIOS = (
    Scenario("2026-08-10-001", "FOIL_001", "Learning session", 104, 7),
    Scenario("2026-08-14-001", "FOIL_002", "Pack 4 thermal anomaly", 208, 8, True),
    Scenario("2026-08-18-001", "FOIL_003", "Ingress safety drill", 312, 6, False, True, True),
)

CONFIG_SNAPSHOTS = {
    "FOIL_001": {
        "name": "Learning",
        "motor_current_max_A": 72,
        "battery_current_max_A": 48,
        "duty_max": 0.90,
        "throttle_ramp_seconds": 0.9,
        "control_mode": "Current No Reverse",
        "write_policy": "read_only_snapshot",
    },
    "FOIL_002": {
        "name": "Cruise",
        "motor_current_max_A": 82,
        "battery_current_max_A": 56,
        "duty_max": 0.93,
        "throttle_ramp_seconds": 0.7,
        "control_mode": "Current No Reverse",
        "write_policy": "read_only_snapshot",
    },
    "FOIL_003": {
        "name": "Safety drill",
        "motor_current_max_A": 68,
        "battery_current_max_A": 44,
        "duty_max": 0.86,
        "throttle_ramp_seconds": 1.0,
        "control_mode": "Current No Reverse",
        "write_policy": "read_only_snapshot",
    },
}


def _state_schedule(scenario: Scenario, hz: int, rng: np.random.Generator) -> np.ndarray:
    states: list[str] = [str(RideState.IDLE)] * (15 * hz)
    for ride in range(scenario.ride_count):
        accelerate_s = int(rng.integers(5, 9))
        states.extend([str(RideState.ACCELERATING)] * (accelerate_s * hz))
        if ride == 1 and scenario.name == "Learning session":
            states.extend([str(RideState.FALL)] * (2 * hz))
            states.extend([str(RideState.IDLE)] * (int(rng.integers(10, 18)) * hz))
            continue
        foil_s = int(rng.integers(25, 75))
        first = foil_s // 2
        states.extend([str(RideState.FOILING)] * (first * hz))
        if ride % 3 != 2:
            states.extend([str(RideState.TOUCHDOWN)] * (2 * hz))
            states.extend([str(RideState.FOILING)] * ((foil_s - first) * hz))
        else:
            states.extend([str(RideState.FOILING)] * ((foil_s - first) * hz))
        states.extend([str(RideState.FALL)] * (2 * hz))
        states.extend([str(RideState.IDLE)] * (int(rng.integers(10, 22)) * hz))
    states.extend([str(RideState.IDLE)] * (20 * hz))
    return np.asarray(states, dtype=object)


def generate_session(scenario: Scenario, hz: int = 10) -> pd.DataFrame:
    rng = np.random.default_rng(scenario.seed)
    state = _state_schedule(scenario, hz, rng)
    count = len(state)
    time_s = np.arange(count) / hz
    timestamp_ms = (time_s * 1000).astype(int)

    speed_target = np.select(
        [
            state == RideState.IDLE,
            state == RideState.ACCELERATING,
            state == RideState.FOILING,
            state == RideState.TOUCHDOWN,
            state == RideState.FALL,
        ],
        [0.15, 3.5, 6.4, 3.2, 0.4],
        default=0.0,
    )
    speed = np.maximum(0.0, speed_target + rng.normal(0.0, 0.22, count))
    power_target = np.select(
        [
            state == RideState.IDLE,
            state == RideState.ACCELERATING,
            state == RideState.FOILING,
            state == RideState.TOUCHDOWN,
            state == RideState.FALL,
        ],
        [8.0, 2350.0, 720.0, 1180.0, 25.0],
        default=0.0,
    )
    power = np.maximum(0.0, power_target * (1 + rng.normal(0.0, 0.08, count)))
    cumulative_wh = np.cumsum(power / hz / 3600.0)
    soc_drop = cumulative_wh / 600.0
    vin = 50.0 - 10.0 * soc_drop - np.clip(power / 2300.0 * 2.4, 0, 2.4)
    battery_a = power / np.maximum(vin, 1.0)
    motor_a = battery_a * np.where(state == RideState.ACCELERATING, 1.65, 1.25)
    duty = np.clip(speed / 8.0 + rng.normal(0, 0.015, count), 0, 0.95)
    erpm = speed * 6900 + rng.normal(0, 160, count)

    heat_load = np.cumsum(power / max(float(power.max()), 1.0)) / hz / 60.0
    pack_temps: dict[str, np.ndarray] = {}
    for pack in range(1, 7):
        pack_temp = 22.0 + heat_load * (0.55 + 0.04 * pack) + rng.normal(0, 0.08, count)
        if scenario.thermal_anomaly and pack == 4:
            pack_temp += np.linspace(0.0, 17.0, count)
        pack_temps[f"pack{pack}_C"] = pack_temp
    mosfet_temp = 24.0 + heat_load * 1.9 + np.clip(power / 1000.0, 0, 3.0)
    safety_temp = 23.0 + heat_load * 0.75
    enclosure_temp = 22.0 + heat_load * 0.4

    vibration_sigma = np.select(
        [state == RideState.FOILING, state == RideState.TOUCHDOWN, state == RideState.FALL],
        [0.055, 0.75, 1.15],
        default=0.18,
    )
    accel_x = rng.normal(0, vibration_sigma)
    accel_y = rng.normal(0, vibration_sigma)
    accel_z = 1.0 + rng.normal(0, vibration_sigma)
    gyro_sigma = np.select(
        [state == RideState.FOILING, state == RideState.TOUCHDOWN, state == RideState.FALL],
        [9.0, 55.0, 155.0],
        default=18.0,
    )
    gyro_x = rng.normal(0, gyro_sigma)
    gyro_y = rng.normal(0, gyro_sigma)
    gyro_z = rng.normal(0, gyro_sigma)

    bearing = np.deg2rad(35 + 18 * np.sin(time_s / 85.0))
    north_m = np.cumsum(speed * np.cos(bearing) / hz)
    east_m = np.cumsum(speed * np.sin(bearing) / hz)
    lat0, lon0 = 40.5524, -105.1628
    gps_lat = lat0 + north_m / 111_111.0
    gps_lon = lon0 + east_m / (111_111.0 * np.cos(np.deg2rad(lat0)))

    water_alarm = np.zeros(count, dtype=bool)
    water_adc = rng.normal(3860, 18, count)
    if scenario.water_ingress:
        alarm_index = int(count * 0.72)
        water_alarm[alarm_index:] = True
        water_adc[alarm_index:] = rng.normal(620, 70, count - alarm_index)
    fault_code = np.zeros(count, dtype=int)
    if scenario.vesc_fault:
        fault_index = int(count * 0.78)
        fault_code[fault_index : fault_index + 5 * hz] = 5

    frame = pd.DataFrame(
        {
            "schema_version": SCHEMA_VERSION,
            "timestamp_ms": timestamp_ms,
            "session_id": scenario.session_id,
            "config_id": scenario.config_id,
            "vesc_vin_V": vin,
            "vesc_battery_A": battery_a,
            "vesc_motor_A": motor_a,
            "vesc_duty": duty,
            "vesc_erpm": erpm,
            "vesc_mosfet_C": mosfet_temp,
            "vesc_motor_or_safety_ntc_C": safety_temp,
            **pack_temps,
            "enclosure_C": enclosure_temp,
            "water_adc": np.clip(water_adc, 0, 4095),
            "water_alarm": water_alarm,
            "accel_x_g": accel_x,
            "accel_y_g": accel_y,
            "accel_z_g": accel_z,
            "gyro_x_dps": gyro_x,
            "gyro_y_dps": gyro_y,
            "gyro_z_dps": gyro_z,
            "amp_hours": np.cumsum(battery_a / hz / 3600.0),
            "watt_hours": cumulative_wh,
            "fault_code": fault_code,
            "remote_ok": True,
            "sd_ok": True,
            "gps_lat": gps_lat,
            "gps_lon": gps_lon,
            "gps_speed_mps": speed,
            "gps_course_deg": np.rad2deg(bearing),
            "gps_fix_quality": 2,
            "sim_state": state,
            "scenario": scenario.name,
        }
    )
    return frame


def write_demo_package(output: Path, config: AppConfig) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    (output / "configs").mkdir(exist_ok=True)
    written: list[Path] = []
    manifest_sessions: list[dict[str, str]] = []
    manifest: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "description": "Deterministic synthetic Jarred Drive sessions; not hardware observations.",
        "sessions": manifest_sessions,
    }
    summaries: list[dict[str, object]] = []
    for config_id, snapshot in CONFIG_SNAPSHOTS.items():
        path = output / "configs" / f"{config_id}.json"
        path.write_text(json.dumps({"config_id": config_id, **snapshot}, indent=2) + "\n")
        written.append(path)
    for scenario in SCENARIOS:
        raw = generate_session(scenario)
        telemetry, events = detect_events(raw, config.detection, use_synthetic_truth=True)
        rides = build_rides(telemetry, events)
        summary = summarize_session(telemetry, events, rides)
        session_dir = output / scenario.session_id
        session_dir.mkdir(exist_ok=True)
        paths = {
            "telemetry": session_dir / "telemetry.csv",
            "events": session_dir / "events.csv",
            "rides": session_dir / "rides.csv",
            "summary": session_dir / "summary.json",
        }
        raw.to_csv(paths["telemetry"], index=False, float_format="%.6f")
        events.to_csv(paths["events"], index=False)
        rides.to_csv(paths["rides"], index=False, float_format="%.4f")
        paths["summary"].write_text(json.dumps(summary, indent=2, default=float) + "\n")
        written.extend(paths.values())
        summaries.append(summary)
        manifest_sessions.append(
            {
                "session_id": scenario.session_id,
                "scenario": scenario.name,
                "config_id": scenario.config_id,
                "directory": scenario.session_id,
            }
        )
    pd.DataFrame(summaries).to_csv(output / "session_index.csv", index=False)
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    written.extend([output / "session_index.csv", manifest_path])
    return written
