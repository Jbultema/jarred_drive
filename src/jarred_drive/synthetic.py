"""Deterministic synthetic sessions for development before hardware exists."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from jarred_drive.analytics import (
    build_crash_dynamics,
    build_electrical_phase_summary,
    build_launch_attempts,
    build_rides,
    build_thermal_analysis,
    summarize_session,
    system_monitoring_summary,
)
from jarred_drive.config import AppConfig
from jarred_drive.events import detect_events
from jarred_drive.schema import SCHEMA_VERSION, RideState
from jarred_drive.sync import MANIFEST_SCHEMA_VERSION, sha256_file


@dataclass(frozen=True)
class Scenario:
    session_id: str
    config_id: str
    name: str
    seed: int
    attempt_count: int
    thermal_anomaly: bool = False
    water_ingress: bool = False
    vesc_fault: bool = False
    launch_crash_indices: tuple[int, ...] = ()
    aborted_launch_indices: tuple[int, ...] = ()


SCENARIOS = (
    Scenario(
        "2026-08-10-001",
        "FOIL_001",
        "Learning session",
        104,
        8,
        launch_crash_indices=(1,),
        aborted_launch_indices=(5,),
    ),
    Scenario("2026-08-14-001", "FOIL_002", "Pack 4 thermal anomaly", 208, 8, True),
    Scenario("2026-08-18-001", "FOIL_003", "Ingress safety drill", 312, 6, False, True, True),
    Scenario(
        "2026-08-11-001",
        "FOIL_004",
        "Commissioning repeat",
        105,
        8,
        aborted_launch_indices=(6,),
    ),
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
    "FOIL_004": {
        "name": "Commissioning repeat",
        "motor_current_max_A": 72,
        "battery_current_max_A": 48,
        "duty_max": 0.90,
        "throttle_ramp_seconds": 0.8,
        "control_mode": "Current No Reverse",
        "write_policy": "read_only_snapshot",
        "synthetic_comparison_note": "Single-parameter fixture relative to FOIL_001",
    },
}


def _state_schedule(
    scenario: Scenario, hz: int, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    states: list[str] = []
    attempts: list[int] = []

    def extend(state: RideState, seconds: int, attempt_id: int = -1) -> None:
        samples = seconds * hz
        states.extend([str(state)] * samples)
        attempts.extend([attempt_id] * samples)

    extend(RideState.IDLE, 15)
    for ride in range(scenario.attempt_count):
        accelerate_s = int(rng.integers(5, 9))
        extend(RideState.ACCELERATING, accelerate_s, ride + 1)
        if ride in scenario.launch_crash_indices:
            extend(RideState.FALL, 2, ride + 1)
            extend(RideState.IDLE, int(rng.integers(10, 18)))
            continue
        if ride in scenario.aborted_launch_indices:
            extend(RideState.IDLE, int(rng.integers(10, 18)))
            continue
        foil_s = int(rng.integers(25, 75))
        first = foil_s // 2
        extend(RideState.FOILING, first, ride + 1)
        if ride % 3 != 2:
            extend(RideState.TOUCHDOWN, 2, ride + 1)
            extend(RideState.FOILING, foil_s - first, ride + 1)
        else:
            extend(RideState.FOILING, foil_s - first, ride + 1)
        extend(RideState.FALL, 2, ride + 1)
        extend(RideState.IDLE, int(rng.integers(10, 22)))
    extend(RideState.IDLE, 20)
    return np.asarray(states, dtype=object), np.asarray(attempts, dtype=int)


def _segment_progress(state: np.ndarray, attempts: np.ndarray) -> np.ndarray:
    """Return 0-1 progress within each contiguous state/attempt segment."""
    progress = np.zeros(len(state), dtype=float)
    start = 0
    for index in range(1, len(state) + 1):
        boundary = (
            index == len(state)
            or state[index] != state[start]
            or attempts[index] != attempts[start]
        )
        if boundary:
            length = index - start
            progress[start:index] = np.linspace(0.0, 1.0, length, endpoint=True)
            start = index
    return progress


def generate_session(scenario: Scenario, hz: int = 10) -> pd.DataFrame:
    rng = np.random.default_rng(scenario.seed)
    state, attempt_id = _state_schedule(scenario, hz, rng)
    count = len(state)
    time_s = np.arange(count) / hz
    timestamp_ms = (time_s * 1000).astype(int)
    dt = 1.0 / hz
    progress = _segment_progress(state, attempt_id)

    outcome = np.full(count, "NONE", dtype=object)
    for attempt in range(1, scenario.attempt_count + 1):
        if attempt - 1 in scenario.launch_crash_indices:
            label = "LAUNCH_CRASH"
        elif attempt - 1 in scenario.aborted_launch_indices:
            label = "FAILED"
        else:
            label = "SUCCESS"
        outcome[attempt_id == attempt] = label

    direction = np.where(attempt_id % 2 == 0, -1.0, 1.0)
    yaw_rate_dps = np.select(
        [
            state == RideState.IDLE,
            state == RideState.ACCELERATING,
            state == RideState.FOILING,
            state == RideState.TOUCHDOWN,
            state == RideState.FALL,
        ],
        [
            0.25 * np.sin(time_s / 9.0),
            direction * (1.2 + 0.8 * np.sin(time_s / 4.0)),
            direction * (5.5 + 4.5 * np.sin(time_s / 7.5 + attempt_id)),
            -direction * (13.0 + 4.0 * np.sin(time_s)),
            direction * 70.0 * np.exp(-4.0 * progress),
        ],
        default=0.0,
    )
    heading_deg = np.mod(28.0 + np.cumsum(yaw_rate_dps) * dt, 360.0)

    speed_target = np.full(count, 0.12)
    accelerating = state == RideState.ACCELERATING
    speed_target[accelerating & (outcome == "SUCCESS")] = 5.25
    speed_target[accelerating & (outcome == "FAILED")] = 2.7
    speed_target[accelerating & (outcome == "LAUNCH_CRASH")] = 3.8
    speed_target[state == RideState.FOILING] = 6.4 + 0.55 * np.sin(
        time_s[state == RideState.FOILING] / 5.5
    )
    speed_target[state == RideState.TOUCHDOWN] = 4.0
    speed_target[state == RideState.FALL] = 0.25
    time_constant = np.select(
        [
            state == RideState.ACCELERATING,
            state == RideState.FOILING,
            state == RideState.TOUCHDOWN,
            state == RideState.FALL,
        ],
        [1.7, 0.9, 0.45, 0.28],
        default=1.8,
    )
    speed = np.zeros(count, dtype=float)
    for index in range(1, count):
        alpha = dt / (float(time_constant[index]) + dt)
        speed[index] = speed[index - 1] + alpha * (speed_target[index] - speed[index - 1])
    speed = np.maximum(0.0, speed + rng.normal(0.0, 0.045, count))

    power = np.full(count, 7.0)
    success_launch = accelerating & (outcome == "SUCCESS")
    failed_launch = accelerating & (outcome == "FAILED")
    crash_launch = accelerating & (outcome == "LAUNCH_CRASH")
    power[success_launch] = (
        380.0
        + 2850.0 * (1.0 - np.exp(-5.2 * progress[success_launch]))
        - 720.0 * progress[success_launch]
    )
    power[failed_launch] = 260.0 + 1750.0 * np.sin(np.pi * progress[failed_launch]) ** 0.8
    power[crash_launch] = (
        450.0
        + 3150.0 * (1.0 - np.exp(-6.0 * progress[crash_launch]))
        - 350.0 * progress[crash_launch]
    )
    foiling = state == RideState.FOILING
    power[foiling] = 420.0 + 12.0 * speed[foiling] ** 2 + 5.0 * np.abs(yaw_rate_dps[foiling])
    power[state == RideState.TOUCHDOWN] = 1050.0 + 420.0 * (
        1.0 - progress[state == RideState.TOUCHDOWN]
    )
    power[state == RideState.FALL] = 25.0
    power = np.maximum(0.0, power * (1.0 + rng.normal(0.0, 0.045, count)))
    cumulative_wh = np.cumsum(power / hz / 3600.0)
    soc_drop = cumulative_wh / 600.0
    open_circuit_v = 50.35 - 10.5 * soc_drop
    estimated_a = power / np.maximum(open_circuit_v, 1.0)
    vin = open_circuit_v - estimated_a * 0.043
    battery_a = power / np.maximum(vin, 1.0)
    motor_a = battery_a * np.where(accelerating, 1.72, 1.27)
    motor_a *= 1.0 + rng.normal(0.0, 0.025, count)
    duty = np.clip(0.035 + speed / 8.0 + rng.normal(0, 0.01, count), 0, 0.95)
    erpm = speed * 6900 + rng.normal(0, 95, count)

    ambient_c = 21.8
    pack_temps: dict[str, np.ndarray] = {}
    for pack in range(1, 7):
        pack_temp = np.empty(count, dtype=float)
        pack_temp[0] = ambient_c + (pack - 3.5) * 0.07
        resistance_factor = 9.2 if scenario.thermal_anomaly and pack == 4 else 1.0 + pack * 0.025
        for index in range(1, count):
            heating = resistance_factor * (battery_a[index] / 55.0) ** 2 * 0.037
            cooling = (pack_temp[index - 1] - ambient_c) / 720.0
            pack_temp[index] = pack_temp[index - 1] + (heating - cooling) * dt
        pack_temp += rng.normal(0, 0.035, count)
        pack_temps[f"pack{pack}_C"] = pack_temp
    mosfet_temp = np.empty(count, dtype=float)
    safety_temp = np.empty(count, dtype=float)
    enclosure_temp = np.empty(count, dtype=float)
    mosfet_temp[0], safety_temp[0], enclosure_temp[0] = 23.0, 22.6, 22.0
    for index in range(1, count):
        mosfet_temp[index] = (
            mosfet_temp[index - 1]
            + ((power[index] / 1000.0) * 0.022 - (mosfet_temp[index - 1] - ambient_c) / 280.0) * dt
        )
        safety_temp[index] = (
            safety_temp[index - 1]
            + ((power[index] / 1000.0) * 0.010 - (safety_temp[index - 1] - ambient_c) / 460.0) * dt
        )
        enclosure_temp[index] = (
            enclosure_temp[index - 1]
            + ((power[index] / 1000.0) * 0.004 - (enclosure_temp[index - 1] - ambient_c) / 900.0)
            * dt
        )

    longitudinal_g = np.gradient(speed, dt) / 9.80665
    lateral_g = speed * np.deg2rad(yaw_rate_dps) / 9.80665
    vibration_sigma = np.select(
        [foiling, state == RideState.TOUCHDOWN, state == RideState.FALL],
        [0.035, 0.18, 0.24],
        default=0.07,
    )
    impact_envelope = np.where(
        state == RideState.FALL, np.exp(-(((progress - 0.18) / 0.10) ** 2)), 0.0
    )
    accel_x = longitudinal_g + rng.normal(0, vibration_sigma)
    accel_y = lateral_g + direction * impact_envelope * 1.35 + rng.normal(0, vibration_sigma)
    accel_z = (
        1.0
        + np.where(foiling, 0.035 * np.sin(time_s * 3.2), 0.0)
        + impact_envelope * 2.1
        + rng.normal(0, vibration_sigma)
    )
    gyro_x = direction * impact_envelope * 310.0 + rng.normal(0, 5.0, count)
    gyro_y = -direction * impact_envelope * 235.0 + rng.normal(0, 5.0, count)
    gyro_z = yaw_rate_dps + direction * impact_envelope * 180.0 + rng.normal(0, 3.0, count)

    bearing = np.deg2rad(heading_deg)
    north_m = np.cumsum(speed * np.cos(bearing) * dt)
    east_m = np.cumsum(speed * np.sin(bearing) * dt)
    lat0, lon0 = 40.5524, -105.1628
    gps_noise_north = rng.normal(0.0, 0.28, count)
    gps_noise_east = rng.normal(0.0, 0.28, count)
    gps_lat = lat0 + (north_m + gps_noise_north) / 111_111.0
    gps_lon = lon0 + (east_m + gps_noise_east) / (111_111.0 * np.cos(np.deg2rad(lat0)))
    gps_speed = np.maximum(0.0, speed + rng.normal(0.0, 0.09, count))
    gps_course = np.mod(heading_deg + rng.normal(0.0, 1.1, count), 360.0)
    gps_fix = np.full(count, 2, dtype=int)
    if scenario.thermal_anomaly:
        dropout_start = int(count * 0.46)
        dropout_end = dropout_start + 22 * hz
        gps_fix[dropout_start:dropout_end] = 0
        gps_lat[dropout_start:dropout_end] = np.nan
        gps_lon[dropout_start:dropout_end] = np.nan
        gps_speed[dropout_start:dropout_end] = np.nan
        gps_course[dropout_start:dropout_end] = np.nan

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
    sd_ok = np.ones(count, dtype=bool)
    if scenario.thermal_anomaly:
        sd_gap = int(count * 0.62)
        sd_ok[sd_gap : sd_gap + 2 * hz] = False

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
            "sd_ok": sd_ok,
            "gps_lat": gps_lat,
            "gps_lon": gps_lon,
            "gps_speed_mps": gps_speed,
            "gps_course_deg": gps_course,
            "gps_fix_quality": gps_fix,
            "sim_state": state,
            "sim_attempt_id": attempt_id,
            "sim_outcome": outcome,
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
    device_path = output / "device.json"
    device_path.write_text(
        json.dumps(
            {
                "device_id": "jarred-drive-sim-01",
                "name": "Jarred Drive Development Logger",
                "hardware_revision": "logger-v1-simulated",
                "firmware_version": "0.3.1-simulated",
                "mode": "SYNC",
                "battery_percent": 83.0,
                "sd_free_percent": 71.0,
                "data_kind": "synthetic",
                "capabilities": {
                    "session_download": True,
                    "range_download": True,
                    "live_status": False,
                    "config_write": False,
                    "peer_upload": False,
                },
            },
            indent=2,
        )
        + "\n"
    )
    written.append(device_path)
    summaries: list[dict[str, object]] = []
    for config_id, snapshot in CONFIG_SNAPSHOTS.items():
        path = output / "configs" / f"{config_id}.json"
        path.write_text(json.dumps({"config_id": config_id, **snapshot}, indent=2) + "\n")
        written.append(path)
    for scenario in SCENARIOS:
        raw = generate_session(scenario)
        telemetry, events = detect_events(raw, config.detection, use_synthetic_truth=True)
        rides = build_rides(telemetry, events)
        launches = build_launch_attempts(telemetry, events)
        crashes = build_crash_dynamics(telemetry, events, config.detection.motor_power_w)
        _, thermal_sensors, thermal_phases = build_thermal_analysis(telemetry)
        electrical_phases = build_electrical_phase_summary(telemetry)
        monitoring = system_monitoring_summary(telemetry)
        summary = summarize_session(telemetry, events, rides)
        session_dir = output / scenario.session_id
        session_dir.mkdir(exist_ok=True)
        paths = {
            "telemetry": session_dir / "telemetry.csv",
            "events": session_dir / "events.csv",
            "rides": session_dir / "rides.csv",
            "launches": session_dir / "launches.csv",
            "crashes": session_dir / "crashes.csv",
            "thermal_sensors": session_dir / "thermal_sensors.csv",
            "thermal_phases": session_dir / "thermal_phases.csv",
            "electrical_phases": session_dir / "electrical_phases.csv",
            "monitoring": session_dir / "monitoring.json",
            "summary": session_dir / "summary.json",
        }
        raw.to_csv(paths["telemetry"], index=False, float_format="%.6f")
        events.to_csv(paths["events"], index=False)
        rides.to_csv(paths["rides"], index=False, float_format="%.4f")
        launches.to_csv(paths["launches"], index=False, float_format="%.4f")
        crashes.to_csv(paths["crashes"], index=False, float_format="%.4f")
        thermal_sensors.to_csv(paths["thermal_sensors"], index=False, float_format="%.4f")
        thermal_phases.to_csv(paths["thermal_phases"], index=False, float_format="%.4f")
        electrical_phases.to_csv(paths["electrical_phases"], index=False, float_format="%.4f")
        paths["monitoring"].write_text(json.dumps(monitoring, indent=2, default=float) + "\n")
        paths["summary"].write_text(json.dumps(summary, indent=2, default=float) + "\n")
        config_path = session_dir / "config.json"
        config_payload = {"config_id": scenario.config_id, **CONFIG_SNAPSHOTS[scenario.config_id]}
        config_path.write_text(json.dumps(config_payload, indent=2) + "\n")
        start = datetime.fromisoformat(f"{scenario.session_id[:10]}T16:00:00").replace(tzinfo=UTC)
        duration_s = float(raw["timestamp_ms"].iloc[-1] - raw["timestamp_ms"].iloc[0]) / 1000.0
        session_manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "telemetry_schema_version": SCHEMA_VERSION,
            "device_id": "jarred-drive-sim-01",
            "session_id": scenario.session_id,
            "start_time_utc": start.isoformat().replace("+00:00", "Z"),
            "end_time_utc": (start + timedelta(seconds=duration_s))
            .isoformat()
            .replace("+00:00", "Z"),
            "duration_s": duration_s,
            "firmware_version": "0.3.1-simulated",
            "hardware_revision": "logger-v1-simulated",
            "vesc_config_id": scenario.config_id,
            "vesc_config_hash": sha256_file(config_path),
            "data_kind": "synthetic",
            "scenario": scenario.name,
            "files": [
                {
                    "name": path.name,
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in (paths["telemetry"], config_path)
            ],
        }
        session_manifest_path = session_dir / "manifest.json"
        session_manifest_path.write_text(json.dumps(session_manifest, indent=2) + "\n")
        written.extend(paths.values())
        written.extend([config_path, session_manifest_path])
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
