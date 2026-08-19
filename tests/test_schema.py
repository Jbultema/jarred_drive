from __future__ import annotations

from jarred_drive.schema import SCHEMA_VERSION, validate_telemetry
from jarred_drive.synthetic import SCENARIOS, generate_session


def test_synthetic_session_satisfies_contract() -> None:
    frame = generate_session(SCENARIOS[0])
    report = validate_telemetry(frame)
    assert report.valid, report.as_dicts()
    assert set(frame["schema_version"]) == {SCHEMA_VERSION}


def test_missing_required_column_is_rejected() -> None:
    frame = generate_session(SCENARIOS[0]).drop(columns=["vesc_vin_V"])
    report = validate_telemetry(frame)
    assert not report.valid
    assert report.issues[0].code == "missing_columns"


def test_duplicate_timestamp_is_rejected() -> None:
    frame = generate_session(SCENARIOS[0])
    frame.loc[1, "timestamp_ms"] = frame.loc[0, "timestamp_ms"]
    report = validate_telemetry(frame)
    assert not report.valid
    assert {issue.code for issue in report.issues} >= {"duplicate_timestamp", "timestamp_order"}


def test_partial_gps_contract_is_rejected() -> None:
    frame = generate_session(SCENARIOS[0]).drop(columns=["gps_course_deg"])
    report = validate_telemetry(frame)
    assert not report.valid
    assert "partial_gps_schema" in {issue.code for issue in report.issues}
