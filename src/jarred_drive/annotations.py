"""Manual event annotations and deterministic merge semantics."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from jarred_drive.schema import EventType

ANNOTATION_COLUMNS = (
    "session_id",
    "timestamp_ms",
    "event_type",
    "confidence",
    "source",
    "notes",
)


def annotation_template(session_id: str) -> pd.DataFrame:
    return pd.DataFrame(columns=ANNOTATION_COLUMNS).astype(
        {
            "session_id": "string",
            "timestamp_ms": "int64",
            "event_type": "string",
            "confidence": "float64",
            "source": "string",
            "notes": "string",
        }
    )


def validate_annotations(frame: pd.DataFrame, session_id: str, max_timestamp_ms: int) -> list[str]:
    errors: list[str] = []
    missing = set(ANNOTATION_COLUMNS) - set(frame.columns)
    if missing:
        return [f"Missing annotation columns: {sorted(missing)}"]
    if not frame.empty and set(frame["session_id"].astype(str)) != {session_id}:
        errors.append("Every annotation must match the selected session")
    valid_events = {str(event) for event in EventType}
    invalid_events = sorted(set(frame["event_type"].dropna().astype(str)) - valid_events)
    if invalid_events:
        errors.append(f"Unknown event types: {invalid_events}")
    if (
        not frame.empty
        and ((frame["timestamp_ms"] < 0) | (frame["timestamp_ms"] > max_timestamp_ms)).any()
    ):
        errors.append("Annotation timestamp falls outside the session")
    return errors


def save_annotations(frame: pd.DataFrame, destination: Path | str) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = frame.loc[:, ANNOTATION_COLUMNS].sort_values("timestamp_ms", kind="stable")
    normalized.to_csv(path, index=False)
    return path


def merge_annotations(events: pd.DataFrame, annotations: pd.DataFrame) -> pd.DataFrame:
    """Combine detected and manual events while preserving provenance.

    A manual event within 500 ms of the same detected type supersedes that
    detection; unrelated detected events are retained.
    """
    if annotations.empty:
        return events.copy()
    keep = pd.Series(True, index=events.index)
    for _, annotation in annotations.iterrows():
        same_type = events["event_type"].astype(str) == str(annotation["event_type"])
        nearby = (events["timestamp_ms"].astype(int) - int(annotation["timestamp_ms"])).abs() <= 500
        keep &= ~(same_type & nearby)
    result = pd.concat([events.loc[keep], annotations], ignore_index=True)
    return result.sort_values("timestamp_ms", kind="stable").reset_index(drop=True)
