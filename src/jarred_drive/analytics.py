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
                "max_speed_mps": float(window.get("gps_speed_mps", pd.Series([np.nan])).max()),
                "peak_power_W": float(window["battery_power_W"].max()),
                "touchdowns": touchdown_count,
                "recoveries": recovery_count,
                "termination": "FALL" if not later_falls.empty else "SESSION_END",
            }
        )
    return pd.DataFrame(rows)


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
