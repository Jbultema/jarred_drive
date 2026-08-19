"""Canonical telemetry schema and validation contracts.

The ESP logger owns raw observations. Every event, ride, and session metric is
derived and can therefore be recomputed as algorithms improve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import pandas as pd

SCHEMA_VERSION = "1.0.0"


class RideState(StrEnum):
    IDLE = "IDLE"
    START_ATTEMPT = "START_ATTEMPT"
    ACCELERATING = "ACCELERATING"
    FOILING = "FOILING"
    TOUCHDOWN = "TOUCHDOWN"
    FALL = "FALL"


class EventType(StrEnum):
    SESSION_START = "SESSION_START"
    SESSION_END = "SESSION_END"
    START_ATTEMPT = "START_ATTEMPT"
    TAKEOFF = "TAKEOFF"
    TOUCHDOWN = "TOUCHDOWN"
    RECOVERY = "RECOVERY"
    FALL = "FALL"
    MOTOR_START = "MOTOR_START"
    MOTOR_STOP = "MOTOR_STOP"
    WATER_DETECTED = "WATER_DETECTED"
    TEMP_WARNING = "TEMP_WARNING"
    VESC_FAULT = "VESC_FAULT"


REQUIRED_COLUMNS: tuple[str, ...] = (
    "schema_version",
    "timestamp_ms",
    "session_id",
    "config_id",
    "vesc_vin_V",
    "vesc_battery_A",
    "vesc_motor_A",
    "vesc_duty",
    "vesc_erpm",
    "vesc_mosfet_C",
    "vesc_motor_or_safety_ntc_C",
    "pack1_C",
    "pack2_C",
    "pack3_C",
    "pack4_C",
    "pack5_C",
    "pack6_C",
    "enclosure_C",
    "water_adc",
    "water_alarm",
    "accel_x_g",
    "accel_y_g",
    "accel_z_g",
    "gyro_x_dps",
    "gyro_y_dps",
    "gyro_z_dps",
    "amp_hours",
    "watt_hours",
    "fault_code",
    "remote_ok",
    "sd_ok",
)

OPTIONAL_GPS_COLUMNS: tuple[str, ...] = (
    "gps_lat",
    "gps_lon",
    "gps_speed_mps",
    "gps_course_deg",
    "gps_fix_quality",
)

SYNTHETIC_ONLY_COLUMNS: tuple[str, ...] = (
    "sim_state",
    "sim_attempt_id",
    "sim_outcome",
    "scenario",
)
PACK_TEMP_COLUMNS: tuple[str, ...] = tuple(f"pack{i}_C" for i in range(1, 7))


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    message: str
    row_count: int = 0


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def as_dicts(self) -> list[dict[str, Any]]:
        return [issue.__dict__ for issue in self.issues]


def validate_telemetry(frame: pd.DataFrame) -> ValidationReport:
    """Validate structure, ordering, ranges, and session invariants."""
    report = ValidationReport()
    missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        report.issues.append(
            ValidationIssue("error", "missing_columns", f"Missing required columns: {missing}")
        )
        return report
    if frame.empty:
        report.issues.append(ValidationIssue("error", "empty_log", "Telemetry log is empty"))
        return report

    versions = set(frame["schema_version"].dropna().astype(str))
    if versions != {SCHEMA_VERSION}:
        report.issues.append(
            ValidationIssue(
                "error", "schema_version", f"Expected {SCHEMA_VERSION}; found {sorted(versions)}"
            )
        )

    duplicate_count = int(frame.duplicated(["session_id", "timestamp_ms"]).sum())
    if duplicate_count:
        report.issues.append(
            ValidationIssue(
                "error",
                "duplicate_timestamp",
                "Duplicate session/timestamp rows detected",
                duplicate_count,
            )
        )

    backwards = 0
    for _, group in frame.groupby("session_id", sort=False):
        backwards += int((group["timestamp_ms"].diff().dropna() <= 0).sum())
    if backwards:
        report.issues.append(
            ValidationIssue(
                "error",
                "timestamp_order",
                "Timestamps must increase within each session",
                backwards,
            )
        )

    range_checks = {
        "vesc_vin_V": (0.0, 60.0),
        "vesc_duty": (-1.0, 1.0),
        "water_adc": (0.0, 4095.0),
        "gps_fix_quality": (0.0, 10.0),
    }
    for column, (low, high) in range_checks.items():
        if column not in frame:
            continue
        invalid = int((~frame[column].between(low, high) & frame[column].notna()).sum())
        if invalid:
            report.issues.append(
                ValidationIssue(
                    "error",
                    "out_of_range",
                    f"{column} must be between {low} and {high}",
                    invalid,
                )
            )

    for column in PACK_TEMP_COLUMNS + ("enclosure_C", "vesc_mosfet_C"):
        invalid = int((~frame[column].between(-20.0, 120.0) & frame[column].notna()).sum())
        if invalid:
            report.issues.append(
                ValidationIssue(
                    "warning",
                    "implausible_temperature",
                    f"{column} contains implausible readings",
                    invalid,
                )
            )

    gps_present = set(OPTIONAL_GPS_COLUMNS).intersection(frame.columns)
    if gps_present and gps_present != set(OPTIONAL_GPS_COLUMNS):
        report.issues.append(
            ValidationIssue(
                "error",
                "partial_gps_schema",
                "GPS data must include all optional GPS columns or none",
            )
        )
    return report
