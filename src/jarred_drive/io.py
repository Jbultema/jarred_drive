"""Filesystem-backed session repository and import helpers."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from jarred_drive.schema import ValidationIssue, ValidationReport, validate_telemetry


@dataclass(frozen=True)
class SessionFiles:
    session_id: str
    directory: Path
    telemetry: Path
    events: Path | None
    rides: Path | None
    summary: Path | None


def discover_sessions(root: Path | str) -> list[SessionFiles]:
    base = Path(root)
    sessions: list[SessionFiles] = []
    if not base.exists():
        return sessions
    for telemetry_path in sorted(base.glob("*/telemetry.csv")):
        directory = telemetry_path.parent
        sessions.append(
            SessionFiles(
                session_id=directory.name,
                directory=directory,
                telemetry=telemetry_path,
                events=(directory / "events.csv") if (directory / "events.csv").exists() else None,
                rides=(directory / "rides.csv") if (directory / "rides.csv").exists() else None,
                summary=(
                    (directory / "summary.json") if (directory / "summary.json").exists() else None
                ),
            )
        )
    return sessions


def read_telemetry(path: Path | str) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    for column in ("water_alarm", "sd_ok"):
        if column in frame:
            if frame[column].dtype == object:
                frame[column] = (
                    frame[column].astype(str).str.lower().map({"true": True, "false": False})
                )
            frame[column] = frame[column].astype(bool)
    if "remote_ok" in frame:
        frame["remote_ok"] = (
            frame["remote_ok"]
            .astype(str)
            .str.lower()
            .map({"true": True, "1": True, "false": False, "0": False})
            .astype("boolean")
        )
    return frame


def read_json(path: Path | str) -> dict[str, object]:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def import_telemetry(source: Path | str, imports_root: Path | str) -> tuple[Path, ValidationReport]:
    """Validate and copy a logger CSV into a session directory without modifying the source."""
    source_path = Path(source)
    frame = read_telemetry(source_path)
    report = validate_telemetry(frame)
    if not report.valid:
        return source_path, report
    session_ids = frame["session_id"].dropna().astype(str).unique()
    if len(session_ids) != 1:
        report.issues.append(
            ValidationIssue(
                "error", "multiple_sessions", "One imported CSV must contain exactly one session"
            )
        )
        return source_path, report
    destination = Path(imports_root) / session_ids[0] / "telemetry.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination)
    return destination, report
