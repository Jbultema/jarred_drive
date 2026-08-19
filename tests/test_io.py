from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from jarred_drive.cli import app
from jarred_drive.io import discover_sessions, import_telemetry, read_telemetry
from jarred_drive.synthetic import SCENARIOS, generate_session


def test_import_valid_log(tmp_path: Path) -> None:
    source = tmp_path / "logger.csv"
    generate_session(SCENARIOS[0]).to_csv(source, index=False)
    destination, report = import_telemetry(source, tmp_path / "imports")
    assert report.valid
    assert destination.exists()
    assert read_telemetry(destination)["session_id"].nunique() == 1


def test_discover_sessions(tmp_path: Path) -> None:
    directory = tmp_path / "S-001"
    directory.mkdir()
    generate_session(SCENARIOS[0]).to_csv(directory / "telemetry.csv", index=False)
    sessions = discover_sessions(tmp_path)
    assert [session.session_id for session in sessions] == ["S-001"]


def test_register_config_for_real_session(tmp_path: Path) -> None:
    source = tmp_path / "snapshot.json"
    source.write_text('{"config_id": "FOIL_099", "battery_current_max_A": 45}')
    output = tmp_path / "configs"
    result = CliRunner().invoke(app, ["register-config", str(source), "--output", str(output)])
    assert result.exit_code == 0
    assert '"write_policy": "read_only_snapshot"' in (output / "FOIL_099.json").read_text()
