from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from jarred_drive.cli import app
from jarred_drive.synthetic import SCENARIOS, generate_session


def test_summarize_exports_full_analysis_package(tmp_path: Path) -> None:
    telemetry_path = tmp_path / "telemetry.csv"
    output_path = tmp_path / "analysis.json"
    generate_session(SCENARIOS[0]).to_csv(telemetry_path, index=False)

    result = CliRunner().invoke(
        app,
        [
            "summarize",
            str(telemetry_path),
            "--output",
            str(output_path),
            "--synthetic-truth",
        ],
    )

    assert result.exit_code == 0, result.output
    for suffix in (
        ".json",
        "_events.csv",
        "_rides.csv",
        "_launches.csv",
        "_crashes.csv",
        "_thermal_sensors.csv",
        "_thermal_phases.csv",
        "_electrical_phases.csv",
        "_monitoring.json",
    ):
        expected = output_path if suffix == ".json" else tmp_path / f"analysis{suffix}"
        assert expected.exists(), expected
