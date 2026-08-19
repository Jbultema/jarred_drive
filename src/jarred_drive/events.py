"""Transparent baseline event detection for foil-assist telemetry.

The baseline is intentionally rule-based and confidence-scored. Manual labels
remain authoritative; future classifiers can replace this module without
changing the raw log contract.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from jarred_drive.config import DetectionConfig
from jarred_drive.schema import EventType, RideState


def add_derived_signals(frame: pd.DataFrame, sample_hz: float | None = None) -> pd.DataFrame:
    result = frame.copy()
    result["battery_power_W"] = result["vesc_vin_V"] * result["vesc_battery_A"]
    result["accel_magnitude_g"] = np.sqrt(
        result["accel_x_g"] ** 2 + result["accel_y_g"] ** 2 + result["accel_z_g"] ** 2
    )
    result["gyro_magnitude_dps"] = np.sqrt(
        result["gyro_x_dps"] ** 2 + result["gyro_y_dps"] ** 2 + result["gyro_z_dps"] ** 2
    )
    if sample_hz is None:
        deltas = result["timestamp_ms"].diff().dropna()
        sample_hz = 1000.0 / float(deltas.median()) if not deltas.empty else 10.0
    window = max(3, int(round(sample_hz)))
    result["vibration_g"] = (
        (result["accel_magnitude_g"] - 1.0).abs().rolling(window, min_periods=1, center=True).mean()
    )
    pack_median = result[[f"pack{i}_C" for i in range(1, 7)]].median(axis=1)
    for index in range(1, 7):
        result[f"pack{index}_delta_C"] = result[f"pack{index}_C"] - pack_median
    return result


def infer_states(frame: pd.DataFrame, config: DetectionConfig) -> pd.DataFrame:
    """Infer a baseline state at every sample from GPS, IMU, and motor telemetry."""
    result = add_derived_signals(frame)
    speed = result.get("gps_speed_mps", pd.Series(np.nan, index=result.index))
    fix = result.get("gps_fix_quality", pd.Series(0, index=result.index)).fillna(0)
    motor_active = result["battery_power_W"] >= config.motor_power_w
    speed_or_erpm = ((fix > 0) & (speed >= config.foil_speed_mps)) | (
        (fix <= 0) & (result["vesc_erpm"].abs() >= config.foil_erpm)
    )
    foil_candidate = speed_or_erpm & (result["vibration_g"] <= config.foil_vibration_g)
    fall_candidate = result["gyro_magnitude_dps"] >= config.fall_gyro_dps

    states: list[str] = []
    previous = RideState.IDLE
    for position in range(len(result)):
        if bool(fall_candidate.iloc[position]):
            state = RideState.FALL
        elif bool(foil_candidate.iloc[position]):
            state = RideState.FOILING
        elif previous == RideState.FOILING and (
            result["vibration_g"].iloc[position] >= config.touchdown_vibration_g
            or (pd.notna(speed.iloc[position]) and speed.iloc[position] > 1.5)
        ):
            state = RideState.TOUCHDOWN
        elif bool(motor_active.iloc[position]):
            state = RideState.ACCELERATING
        else:
            state = RideState.IDLE
        states.append(str(state))
        previous = state
    result["state_inferred"] = states
    return result


def _confidence_for_state(row: pd.Series, state: str, config: DetectionConfig) -> float:
    if state == RideState.FOILING:
        gps_speed = row.get("gps_speed_mps", 0.0)
        speed_score = (
            min(1.0, float(gps_speed) / config.foil_speed_mps)
            if pd.notna(gps_speed)
            else min(1.0, abs(float(row["vesc_erpm"])) / config.foil_erpm)
        )
        vibration_score = max(0.0, 1.0 - float(row["vibration_g"]) / config.foil_vibration_g)
        return round(0.55 + 0.25 * speed_score + 0.20 * vibration_score, 3)
    if state == RideState.FALL:
        return round(min(0.99, 0.6 + float(row["gyro_magnitude_dps"]) / 1000.0), 3)
    return 0.8


def detect_events(
    frame: pd.DataFrame,
    config: DetectionConfig,
    *,
    use_synthetic_truth: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return telemetry with states and a normalized event table."""
    telemetry = add_derived_signals(frame)
    if use_synthetic_truth and "sim_state" in telemetry:
        telemetry["state_inferred"] = telemetry["sim_state"].astype(str)
    else:
        telemetry = infer_states(telemetry, config)

    state = telemetry["state_inferred"].astype(str)
    previous = state.shift(1)
    events: list[dict[str, object]] = []

    def append_event(index: int, event_type: EventType, confidence: float, source: str) -> None:
        row = telemetry.iloc[index]
        events.append(
            {
                "session_id": row["session_id"],
                "timestamp_ms": int(row["timestamp_ms"]),
                "event_type": str(event_type),
                "confidence": round(confidence, 3),
                "source": source,
                "notes": "",
            }
        )

    append_event(0, EventType.SESSION_START, 1.0, "system")
    motor_active = telemetry["battery_power_W"] >= config.motor_power_w
    motor_previous = motor_active.shift(1, fill_value=False)
    for index in np.flatnonzero((motor_active & ~motor_previous).to_numpy()):
        append_event(int(index), EventType.MOTOR_START, 0.95, "baseline")
    for index in np.flatnonzero((~motor_active & motor_previous).to_numpy()):
        append_event(int(index), EventType.MOTOR_STOP, 0.95, "baseline")

    for position in range(1, len(telemetry)):
        current = state.iloc[position]
        prior = previous.iloc[position]
        event_type: EventType | None = None
        if current == RideState.ACCELERATING and current != prior:
            event_type = EventType.START_ATTEMPT
        elif current == RideState.FOILING and prior == RideState.ACCELERATING:
            event_type = EventType.TAKEOFF
        elif current == RideState.TOUCHDOWN and current != prior:
            event_type = EventType.TOUCHDOWN
        elif current == RideState.FALL and current != prior:
            event_type = EventType.FALL
        if event_type is not None:
            append_event(
                position,
                event_type,
                _confidence_for_state(telemetry.iloc[position], current, config),
                "synthetic_truth" if use_synthetic_truth else "baseline",
            )
        if prior == RideState.TOUCHDOWN and current == RideState.FOILING:
            append_event(position, EventType.RECOVERY, 0.85, "baseline")

    alarm_start = telemetry["water_alarm"].astype(bool) & ~telemetry["water_alarm"].astype(
        bool
    ).shift(1, fill_value=False)
    for index in np.flatnonzero(alarm_start.to_numpy()):
        append_event(int(index), EventType.WATER_DETECTED, 1.0, "sensor")

    pack_columns = [f"pack{i}_C" for i in range(1, 7)]
    pack_median = telemetry[pack_columns].median(axis=1)
    pack_delta = telemetry[pack_columns].sub(pack_median, axis=0).max(axis=1)
    hot = (telemetry[pack_columns].max(axis=1) >= 45.0) | (pack_delta >= 7.0)
    if bool(hot.any()):
        first_hot = int(np.flatnonzero(hot.to_numpy())[0])
        append_event(first_hot, EventType.TEMP_WARNING, 1.0, "sensor")

    fault = telemetry["fault_code"].astype(int) != 0
    fault_start = fault & ~fault.shift(1, fill_value=False)
    for index in np.flatnonzero(fault_start.to_numpy()):
        append_event(int(index), EventType.VESC_FAULT, 1.0, "vesc")

    append_event(len(telemetry) - 1, EventType.SESSION_END, 1.0, "system")
    event_frame = (
        pd.DataFrame(events).sort_values("timestamp_ms", kind="stable").reset_index(drop=True)
    )
    return telemetry, event_frame


def estimate_sample_hz(frame: pd.DataFrame) -> float:
    deltas = frame["timestamp_ms"].diff().dropna()
    return 1000.0 / float(deltas.median()) if not deltas.empty else math.nan
