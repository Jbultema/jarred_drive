from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

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


def test_serve_demo_reports_synthetic_source(tmp_path: Path) -> None:
    demo = tmp_path / "demo"
    from jarred_drive.config import load_config
    from jarred_drive.synthetic import write_demo_package

    write_demo_package(demo, load_config())
    server = MagicMock()
    server.server_port = 8765
    server.serve_forever.side_effect = KeyboardInterrupt
    with patch("jarred_drive.cli.create_demo_server", return_value=server):
        result = CliRunner().invoke(app, ["serve-demo", "--source", str(demo)])

    assert result.exit_code == 0, result.output
    assert "Synthetic development logger" in result.output
    assert "not hardware observations" in result.output
    server.server_close.assert_called_once()
