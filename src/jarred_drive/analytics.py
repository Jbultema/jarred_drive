"""Session, ride, equipment-health, and progression analytics."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from jarred_drive.config import SafetyConfig
from jarred_drive.schema import PACK_TEMP_COLUMNS, EventType, RideState


@dataclass(frozen=True)
class HealthStatus:
    level: str
    headline: str
    reasons: tuple[str, ...]


def _duration_seconds(frame: pd.DataFrame) -> float:
    return float(frame["timestamp_ms"].iloc[-1] - frame["timestamp_ms"].iloc[0]) / 1000.0


def _sample_interval_seconds(frame: pd.DataFrame) -> float:
    deltas = frame["timestamp_ms"].diff().dropna()
    return float(deltas.median()) / 1000.0 if not deltas.empty else 0.1


def _gps_series(frame: pd.DataFrame) -> pd.Series:
    return frame.get("gps_speed_mps", pd.Series(np.nan, index=frame.index, dtype=float))


def _first_event_between(source: pd.DataFrame, start_ms: int, end_ms: int) -> int | None:
    candidates = source[source["timestamp_ms"].between(start_ms, end_ms, inclusive="left")]
    return int(candidates.iloc[0]["timestamp_ms"]) if not candidates.empty else None


def health_status(frame: pd.DataFrame, safety: SafetyConfig) -> HealthStatus:
    reasons: list[str] = []
    critical = False
    max_pack = float(frame[list(PACK_TEMP_COLUMNS)].max(axis=1).max())
    pack_deltas = (
        frame[[f"pack{i}_delta_C" for i in range(1, 7)]] if "pack1_delta_C" in frame else None
    )
    max_delta = float(pack_deltas.max(axis=1).max()) if pack_deltas is not None else 0.0
    if bool(frame["water_alarm"].any()):
        critical = True
        reasons.append("Water ingress alarm latched")
    if int(frame["fault_code"].max()) != 0:
        critical = True
        reasons.append("VESC fault recorded")
    if max_pack >= safety.pack_critical_c:
        critical = True
        reasons.append(f"Critical pack temperature {max_pack:.1f}°C")
    elif max_pack >= safety.pack_warning_c:
        reasons.append(f"Pack temperature warning {max_pack:.1f}°C")
    if max_delta >= safety.pack_delta_warning_c:
        reasons.append(f"Pack thermal spread anomaly {max_delta:.1f}°C")
    if float(frame["vesc_mosfet_C"].max()) >= safety.mosfet_warning_c:
        reasons.append("VESC MOSFET temperature warning")
    remote_status = frame["remote_ok"].iloc[-1]
    if pd.isna(remote_status):
        reasons.append("Remote status unavailable in passive UART telemetry")
    elif not bool(remote_status):
        critical = True
        reasons.append("Remote status not OK")
    if not bool(frame["sd_ok"].iloc[-1]):
        reasons.append("SD logger status not OK")
    if critical:
        return HealthStatus("STOP", "STOP SYSTEM", tuple(reasons))
    if reasons:
        return HealthStatus("WARNING", "REVIEW BEFORE NEXT SESSION", tuple(reasons))
    return HealthStatus("READY", "SYSTEM READY", ("No monitored faults",))


def build_rides(telemetry: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    takeoffs = events[events["event_type"] == EventType.TAKEOFF]
    falls = events[events["event_type"] == EventType.FALL]
    for ride_number, (_, takeoff) in enumerate(takeoffs.iterrows(), start=1):
        later_falls = falls[falls["timestamp_ms"] > int(takeoff["timestamp_ms"])]
        end_ms = (
            int(later_falls.iloc[0]["timestamp_ms"])
            if not later_falls.empty
            else int(telemetry["timestamp_ms"].iloc[-1])
        )
        next_takeoffs = takeoffs[takeoffs["timestamp_ms"] > int(takeoff["timestamp_ms"])]
        if not next_takeoffs.empty and int(next_takeoffs.iloc[0]["timestamp_ms"]) < end_ms:
            continue
        window = telemetry[telemetry["timestamp_ms"].between(int(takeoff["timestamp_ms"]), end_ms)]
        if window.empty:
            continue
        state = window["state_inferred"].astype(str)
        dt = float(window["timestamp_ms"].diff().median()) / 1000.0
        foil_seconds = float((state == RideState.FOILING).sum()) * dt
        energy = float(window["watt_hours"].iloc[-1] - window["watt_hours"].iloc[0])
        power = window["battery_power_W"]
        speed = _gps_series(window)
        pack_max = window[list(PACK_TEMP_COLUMNS)].max(axis=1)
        gyro = window["gyro_magnitude_dps"]
        vibration = window["vibration_g"]
        foil_window = window.loc[state == RideState.FOILING]
        turning_fraction = (
            float((foil_window["gyro_z_dps"].abs() >= 4.0).mean()) if not foil_window.empty else 0.0
        )
        touchdown_count = int(
            events[
                (events["event_type"] == EventType.TOUCHDOWN)
                & events["timestamp_ms"].between(int(takeoff["timestamp_ms"]), end_ms)
            ].shape[0]
        )
        recovery_count = int(
            events[
                (events["event_type"] == EventType.RECOVERY)
                & events["timestamp_ms"].between(int(takeoff["timestamp_ms"]), end_ms)
            ].shape[0]
        )
        rows.append(
            {
                "session_id": takeoff["session_id"],
                "ride_id": ride_number,
                "takeoff_ms": int(takeoff["timestamp_ms"]),
                "end_ms": end_ms,
                "ride_seconds": (end_ms - int(takeoff["timestamp_ms"])) / 1000.0,
                "foil_seconds": foil_seconds,
                "energy_Wh": max(0.0, energy),
                "max_speed_mps": float(speed.max()),
                "mean_speed_mps": float(speed.mean()),
                "peak_power_W": float(power.max()),
                "mean_power_W": float(power.mean()),
                "energy_per_foil_min_Wh": max(0.0, energy) / max(foil_seconds / 60.0, 1e-9),
                "minimum_voltage_V": float(window["vesc_vin_V"].min()),
                "mean_duty": float(window["vesc_duty"].mean()),
                "p95_vibration_g": float(vibration.quantile(0.95)),
                "rms_gyro_dps": float(np.sqrt(np.mean(np.square(gyro)))),
                "peak_gyro_dps": float(gyro.max()),
                "turning_fraction": turning_fraction,
                "mean_abs_yaw_rate_dps": (
                    float(foil_window["gyro_z_dps"].abs().mean()) if not foil_window.empty else 0.0
                ),
                "p95_lateral_accel_g": (
                    float(foil_window["accel_y_g"].abs().quantile(0.95))
                    if not foil_window.empty
                    else 0.0
                ),
                "pack_temp_rise_C": float(pack_max.iloc[-1] - pack_max.iloc[0]),
                "vesc_temp_rise_C": float(
                    window["vesc_mosfet_C"].iloc[-1] - window["vesc_mosfet_C"].iloc[0]
                ),
                "touchdowns": touchdown_count,
                "recoveries": recovery_count,
                "termination": "FALL" if not later_falls.empty else "SESSION_END",
            }
        )
    return pd.DataFrame(rows)


def build_launch_attempts(telemetry: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Build one diagnostic row per inferred or manually corrected launch attempt."""
    starts = events[events["event_type"] == EventType.START_ATTEMPT].sort_values("timestamp_ms")
    takeoffs = events[events["event_type"] == EventType.TAKEOFF]
    falls = events[events["event_type"] == EventType.FALL]
    motor_stops = events[events["event_type"] == EventType.MOTOR_STOP]
    session_end = int(telemetry["timestamp_ms"].iloc[-1])
    rows: list[dict[str, object]] = []

    for attempt_id, (_, start) in enumerate(starts.iterrows(), start=1):
        start_ms = int(start["timestamp_ms"])
        later_starts = starts[starts["timestamp_ms"] > start_ms]
        boundary_ms = (
            int(later_starts.iloc[0]["timestamp_ms"]) if not later_starts.empty else session_end
        )

        takeoff_ms = _first_event_between(takeoffs, start_ms, boundary_ms)
        fall_ms = _first_event_between(falls, start_ms, boundary_ms)
        stop_ms = _first_event_between(motor_stops, start_ms, boundary_ms)
        if takeoff_ms is not None:
            outcome = "SUCCESS"
            end_ms = takeoff_ms
        elif fall_ms is not None and (stop_ms is None or fall_ms <= stop_ms):
            outcome = "LAUNCH_CRASH"
            end_ms = fall_ms
        else:
            outcome = "FAILED"
            end_ms = stop_ms if stop_ms is not None else boundary_ms
        end_ms = max(start_ms, end_ms)
        window = telemetry[telemetry["timestamp_ms"].between(start_ms, end_ms)]
        if window.empty:
            continue

        power = window["battery_power_W"].clip(lower=0.0)
        peak_power = float(power.max())
        peak_position = int(power.to_numpy().argmax())
        peak_ms = int(window.iloc[peak_position]["timestamp_ms"])
        threshold_10 = power >= peak_power * 0.10
        threshold_90 = power >= peak_power * 0.90
        time_10_ms = int(window.loc[threshold_10, "timestamp_ms"].iloc[0])
        time_90_ms = int(window.loc[threshold_90, "timestamp_ms"].iloc[0])
        baseline = telemetry[
            telemetry["timestamp_ms"].between(
                max(int(telemetry["timestamp_ms"].iloc[0]), start_ms - 3000), start_ms
            )
        ]
        baseline_voltage = float(baseline["vesc_vin_V"].median())
        min_voltage = float(window["vesc_vin_V"].min())
        pack_max = window[list(PACK_TEMP_COLUMNS)].max(axis=1)
        speed = _gps_series(window)
        duration_s = max((end_ms - start_ms) / 1000.0, _sample_interval_seconds(telemetry))
        energy_wh = float(window["watt_hours"].iloc[-1] - window["watt_hours"].iloc[0])
        rows.append(
            {
                "session_id": start["session_id"],
                "attempt_id": attempt_id,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "outcome": outcome,
                "duration_s": duration_s,
                "time_to_takeoff_s": (
                    (takeoff_ms - start_ms) / 1000.0 if takeoff_ms is not None else np.nan
                ),
                "time_to_peak_power_s": (peak_ms - start_ms) / 1000.0,
                "power_10_90_s": max(0.0, (time_90_ms - time_10_ms) / 1000.0),
                "peak_power_W": peak_power,
                "mean_power_W": float(power.mean()),
                "launch_energy_Wh": max(0.0, energy_wh),
                "peak_battery_A": float(window["vesc_battery_A"].max()),
                "peak_motor_A": float(window["vesc_motor_A"].max()),
                "peak_duty": float(window["vesc_duty"].max()),
                "peak_erpm": float(window["vesc_erpm"].abs().max()),
                "peak_speed_mps": float(speed.max()),
                "takeoff_speed_mps": float(speed.iloc[-1]) if takeoff_ms is not None else np.nan,
                "baseline_voltage_V": baseline_voltage,
                "minimum_voltage_V": min_voltage,
                "voltage_sag_V": max(0.0, baseline_voltage - min_voltage),
                "sag_per_kW_V": max(0.0, baseline_voltage - min_voltage)
                / max(peak_power / 1000.0, 1e-9),
                "peak_accel_delta_g": float((window["accel_magnitude_g"] - 1.0).abs().max()),
                "peak_gyro_dps": float(window["gyro_magnitude_dps"].max()),
                "start_pack_max_C": float(pack_max.iloc[0]),
                "end_pack_max_C": float(pack_max.iloc[-1]),
                "pack_rise_C": float(pack_max.iloc[-1] - pack_max.iloc[0]),
                "peak_pack_spread_C": float(
                    (
                        window[list(PACK_TEMP_COLUMNS)].max(axis=1)
                        - window[list(PACK_TEMP_COLUMNS)].min(axis=1)
                    ).max()
                ),
                "start_vesc_C": float(window["vesc_mosfet_C"].iloc[0]),
                "end_vesc_C": float(window["vesc_mosfet_C"].iloc[-1]),
                "vesc_rise_C": float(
                    window["vesc_mosfet_C"].iloc[-1] - window["vesc_mosfet_C"].iloc[0]
                ),
            }
        )
    return pd.DataFrame(rows)


def build_launch_curves(telemetry: pd.DataFrame, attempts: pd.DataFrame) -> pd.DataFrame:
    """Return sample-level telemetry aligned to the beginning of every launch attempt."""
    curves: list[pd.DataFrame] = []
    for attempt in attempts.itertuples(index=False):
        window = telemetry[
            telemetry["timestamp_ms"].between(attempt.start_ms, attempt.end_ms)
        ].copy()
        if window.empty:
            continue
        window["attempt_id"] = int(attempt.attempt_id)
        window["outcome"] = str(attempt.outcome)
        window["attempt_seconds"] = (window["timestamp_ms"] - int(attempt.start_ms)) / 1000.0
        window["power_kW"] = window["battery_power_W"] / 1000.0
        window["speed_mph"] = _gps_series(window) * 2.23694
        window["pack_max_C"] = window[list(PACK_TEMP_COLUMNS)].max(axis=1)
        curves.append(window)
    return pd.concat(curves, ignore_index=True) if curves else pd.DataFrame()


def build_crash_dynamics(
    telemetry: pd.DataFrame, events: pd.DataFrame, motor_power_w: float = 180.0
) -> pd.DataFrame:
    """Characterize every fall using a three-second lead-in and 1.5-second impact window."""
    falls = events[events["event_type"] == EventType.FALL].sort_values("timestamp_ms")
    starts = events[events["event_type"] == EventType.START_ATTEMPT].sort_values("timestamp_ms")
    takeoffs = events[events["event_type"] == EventType.TAKEOFF].sort_values("timestamp_ms")
    rows: list[dict[str, object]] = []
    session_start = int(telemetry["timestamp_ms"].iloc[0])
    session_end = int(telemetry["timestamp_ms"].iloc[-1])

    for crash_id, (_, fall) in enumerate(falls.iterrows(), start=1):
        fall_ms = int(fall["timestamp_ms"])
        prior_starts = starts[starts["timestamp_ms"] <= fall_ms]
        prior_takeoffs = takeoffs[takeoffs["timestamp_ms"] <= fall_ms]
        last_start = int(prior_starts.iloc[-1]["timestamp_ms"]) if not prior_starts.empty else None
        last_takeoff = (
            int(prior_takeoffs.iloc[-1]["timestamp_ms"]) if not prior_takeoffs.empty else None
        )
        crash_type = (
            "LAUNCH_CRASH"
            if last_start is not None and (last_takeoff is None or last_start > last_takeoff)
            else "RIDE_FALL"
        )
        lead = telemetry[
            telemetry["timestamp_ms"].between(max(session_start, fall_ms - 3000), fall_ms)
        ]
        impact = telemetry[
            telemetry["timestamp_ms"].between(fall_ms, min(session_end, fall_ms + 1500))
        ]
        after = telemetry[telemetry["timestamp_ms"] >= fall_ms]
        motor_off = after[after["battery_power_W"] < motor_power_w]
        cut_latency_ms = (
            int(motor_off.iloc[0]["timestamp_ms"]) - fall_ms if not motor_off.empty else np.nan
        )
        pre = lead.iloc[-1]
        speed = _gps_series(lead)
        rows.append(
            {
                "session_id": fall["session_id"],
                "crash_id": crash_id,
                "timestamp_ms": fall_ms,
                "crash_type": crash_type,
                "time_since_takeoff_s": (
                    (fall_ms - last_takeoff) / 1000.0
                    if last_takeoff is not None and crash_type == "RIDE_FALL"
                    else np.nan
                ),
                "pre_speed_mps": float(speed.iloc[-1]) if not speed.empty else np.nan,
                "pre_power_W": float(pre["battery_power_W"]),
                "pre_duty": float(pre["vesc_duty"]),
                "minimum_voltage_V": float(lead["vesc_vin_V"].min()),
                "peak_accel_delta_g": float((impact["accel_magnitude_g"] - 1.0).abs().max()),
                "peak_gyro_dps": float(impact["gyro_magnitude_dps"].max()),
                "peak_gyro_x_dps": float(impact["gyro_x_dps"].abs().max()),
                "peak_gyro_y_dps": float(impact["gyro_y_dps"].abs().max()),
                "peak_gyro_z_dps": float(impact["gyro_z_dps"].abs().max()),
                "motor_cut_latency_ms": cut_latency_ms,
            }
        )
    return pd.DataFrame(rows)


def build_thermal_analysis(
    telemetry: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return enriched thermal traces plus sensor and operating-phase summaries."""
    trace = telemetry.copy()
    trace["session_seconds"] = (trace["timestamp_ms"] - int(trace["timestamp_ms"].iloc[0])) / 1000.0
    trace["pack_mean_C"] = trace[list(PACK_TEMP_COLUMNS)].mean(axis=1)
    trace["pack_max_C"] = trace[list(PACK_TEMP_COLUMNS)].max(axis=1)
    trace["pack_min_C"] = trace[list(PACK_TEMP_COLUMNS)].min(axis=1)
    trace["pack_spread_C"] = trace["pack_max_C"] - trace["pack_min_C"]
    thermal_sensors = list(PACK_TEMP_COLUMNS) + [
        "vesc_mosfet_C",
        "vesc_motor_or_safety_ntc_C",
        "enclosure_C",
    ]
    dt = _sample_interval_seconds(trace)
    slope_rows = max(1, int(round(10.0 / max(dt, 1e-6))))
    elapsed = trace["session_seconds"].diff(slope_rows)
    for sensor in thermal_sensors:
        trace[f"{sensor}_rate_C_min"] = trace[sensor].diff(slope_rows) / elapsed * 60.0

    sensor_rows: list[dict[str, object]] = []
    phase_rows: list[dict[str, object]] = []
    for sensor in thermal_sensors:
        rates = trace[f"{sensor}_rate_C_min"]
        sensor_rows.append(
            {
                "sensor": sensor,
                "start_C": float(trace[sensor].iloc[0]),
                "end_C": float(trace[sensor].iloc[-1]),
                "rise_C": float(trace[sensor].iloc[-1] - trace[sensor].iloc[0]),
                "mean_C": float(trace[sensor].mean()),
                "p95_C": float(trace[sensor].quantile(0.95)),
                "peak_C": float(trace[sensor].max()),
                "peak_heat_rate_C_min": float(rates.max()),
                "minimum_cool_rate_C_min": float(rates.min()),
            }
        )
        for phase, group in trace.groupby(trace["state_inferred"].astype(str), sort=False):
            phase_rows.append(
                {
                    "phase": phase,
                    "sensor": sensor,
                    "samples": len(group),
                    "seconds": len(group) * dt,
                    "mean_C": float(group[sensor].mean()),
                    "p95_C": float(group[sensor].quantile(0.95)),
                    "peak_C": float(group[sensor].max()),
                    "mean_heat_rate_C_min": float(group[f"{sensor}_rate_C_min"].mean()),
                }
            )
    return trace, pd.DataFrame(sensor_rows), pd.DataFrame(phase_rows)


def build_electrical_phase_summary(telemetry: pd.DataFrame) -> pd.DataFrame:
    """Summarize electrical load, voltage sag, and energy for every inferred operating phase."""
    dt = _sample_interval_seconds(telemetry)
    baseline_voltage = float(
        telemetry.loc[telemetry["battery_power_W"] < 180.0, "vesc_vin_V"].median()
    )
    if np.isnan(baseline_voltage):
        baseline_voltage = float(telemetry["vesc_vin_V"].max())
    rows: list[dict[str, object]] = []
    for phase, group in telemetry.groupby(telemetry["state_inferred"].astype(str), sort=False):
        rows.append(
            {
                "phase": phase,
                "seconds": len(group) * dt,
                "energy_Wh": float(group["battery_power_W"].clip(lower=0).sum() * dt / 3600.0),
                "mean_power_W": float(group["battery_power_W"].mean()),
                "p95_power_W": float(group["battery_power_W"].quantile(0.95)),
                "peak_power_W": float(group["battery_power_W"].max()),
                "peak_battery_A": float(group["vesc_battery_A"].max()),
                "peak_motor_A": float(group["vesc_motor_A"].max()),
                "minimum_voltage_V": float(group["vesc_vin_V"].min()),
                "maximum_sag_V": max(0.0, baseline_voltage - float(group["vesc_vin_V"].min())),
                "mean_duty": float(group["vesc_duty"].mean()),
                "p95_erpm": float(group["vesc_erpm"].abs().quantile(0.95)),
            }
        )
    return pd.DataFrame(rows)


def system_monitoring_summary(telemetry: pd.DataFrame) -> dict[str, float | int]:
    """Calculate logger integrity, sensor availability, and electrical envelope metrics."""
    deltas = telemetry["timestamp_ms"].diff().dropna()
    median_ms = float(deltas.median()) if not deltas.empty else np.nan
    gap_threshold = median_ms * 1.5 if not np.isnan(median_ms) else np.inf
    gps_fix = telemetry.get("gps_fix_quality", pd.Series(0, index=telemetry.index)).fillna(0)
    remote = telemetry["remote_ok"]
    numeric = telemetry.select_dtypes(include=[np.number])
    return {
        "sample_rate_hz": 1000.0 / median_ms if median_ms > 0 else np.nan,
        "samples": len(telemetry),
        "maximum_gap_ms": float(deltas.max()) if not deltas.empty else 0.0,
        "gap_count": int((deltas > gap_threshold).sum()),
        "timestamp_jitter_p95_ms": (
            float((deltas - median_ms).abs().quantile(0.95)) if not deltas.empty else 0.0
        ),
        "numeric_completeness": float(numeric.notna().sum().sum() / max(1, numeric.size)),
        "gps_fix_fraction": float((gps_fix > 0).mean()),
        "remote_known_fraction": float(remote.notna().mean()),
        "sd_ok_fraction": float(telemetry["sd_ok"].fillna(False).astype(bool).mean()),
        "fault_samples": int((telemetry["fault_code"] != 0).sum()),
        "fault_codes": int(telemetry.loc[telemetry["fault_code"] != 0, "fault_code"].nunique()),
        "water_alarm_samples": int(telemetry["water_alarm"].astype(bool).sum()),
        "minimum_water_adc": float(telemetry["water_adc"].min()),
        "minimum_voltage_V": float(telemetry["vesc_vin_V"].min()),
        "voltage_range_V": float(telemetry["vesc_vin_V"].max() - telemetry["vesc_vin_V"].min()),
        "peak_battery_A": float(telemetry["vesc_battery_A"].max()),
        "peak_motor_A": float(telemetry["vesc_motor_A"].max()),
        "peak_duty": float(telemetry["vesc_duty"].max()),
    }


def summarize_session(
    telemetry: pd.DataFrame, events: pd.DataFrame, rides: pd.DataFrame
) -> dict[str, object]:
    duration_s = _duration_seconds(telemetry)
    dt = float(telemetry["timestamp_ms"].diff().median()) / 1000.0
    state = telemetry["state_inferred"].astype(str)
    foil_seconds = float((state == RideState.FOILING).sum()) * dt
    assist_seconds = float((telemetry["battery_power_W"] >= 180.0).sum()) * dt
    attempts = int((events["event_type"] == EventType.START_ATTEMPT).sum())
    launches = int((events["event_type"] == EventType.TAKEOFF).sum())
    launch_attempts = build_launch_attempts(telemetry, events)
    crashes = build_crash_dynamics(telemetry, events)
    failed_launches = (
        int((launch_attempts["outcome"] != "SUCCESS").sum()) if not launch_attempts.empty else 0
    )
    energy_wh = float(telemetry["watt_hours"].iloc[-1] - telemetry["watt_hours"].iloc[0])
    gps_available = "gps_speed_mps" in telemetry and telemetry["gps_speed_mps"].notna().any()
    distance_m = 0.0
    if gps_available:
        distance_m = float(
            (telemetry["gps_speed_mps"] * telemetry["timestamp_ms"].diff().fillna(0) / 1000.0).sum()
        )
    return {
        "session_id": str(telemetry["session_id"].iloc[0]),
        "config_id": str(telemetry["config_id"].iloc[0]),
        "scenario": str(telemetry.get("scenario", pd.Series(["imported"])).iloc[0]),
        "duration_seconds": duration_s,
        "assist_seconds": assist_seconds,
        "foil_seconds": foil_seconds,
        "foil_utilization": foil_seconds / duration_s if duration_s else 0.0,
        "attempts": attempts,
        "launches": launches,
        "launch_success": launches / attempts if attempts else 0.0,
        "failed_launches": failed_launches,
        "failed_launch_rate": failed_launches / attempts if attempts else 0.0,
        "launch_crashes": (
            int((crashes["crash_type"] == "LAUNCH_CRASH").sum()) if not crashes.empty else 0
        ),
        "ride_falls": int((crashes["crash_type"] == "RIDE_FALL").sum()) if not crashes.empty else 0,
        "median_time_to_takeoff_seconds": (
            float(launch_attempts["time_to_takeoff_s"].median())
            if not launch_attempts.empty
            else 0.0
        ),
        "median_launch_energy_Wh": (
            float(launch_attempts["launch_energy_Wh"].median())
            if not launch_attempts.empty
            else 0.0
        ),
        "rides": int(len(rides)),
        "touchdowns": int((events["event_type"] == EventType.TOUCHDOWN).sum()),
        "recoveries": int((events["event_type"] == EventType.RECOVERY).sum()),
        "falls": int((events["event_type"] == EventType.FALL).sum()),
        "longest_ride_seconds": float(rides["ride_seconds"].max()) if not rides.empty else 0.0,
        "median_ride_seconds": float(rides["ride_seconds"].median()) if not rides.empty else 0.0,
        "energy_Wh": energy_wh,
        "peak_power_W": float(telemetry["battery_power_W"].max()),
        "peak_battery_A": float(telemetry["vesc_battery_A"].max()),
        "peak_vesc_C": float(telemetry["vesc_mosfet_C"].max()),
        "peak_pack_C": float(telemetry[list(PACK_TEMP_COLUMNS)].max(axis=1).max()),
        "max_pack_spread_C": float(
            (
                telemetry[list(PACK_TEMP_COLUMNS)].max(axis=1)
                - telemetry[list(PACK_TEMP_COLUMNS)].min(axis=1)
            ).max()
        ),
        "distance_m": distance_m,
        "max_speed_mps": float(telemetry["gps_speed_mps"].max()) if gps_available else np.nan,
        "water_detected": bool(telemetry["water_alarm"].any()),
        "vesc_faults": int((telemetry["fault_code"] != 0).sum()),
    }


def health_as_dict(status: HealthStatus) -> dict[str, object]:
    return asdict(status)
