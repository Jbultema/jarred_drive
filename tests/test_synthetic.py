from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from jarred_drive.config import load_config
from jarred_drive.synthetic import SCENARIOS, generate_session, write_demo_package


def test_generation_is_deterministic() -> None:
    first = generate_session(SCENARIOS[0])
    second = generate_session(SCENARIOS[0])
    pd.testing.assert_frame_equal(first, second)


def test_demo_package_contains_three_scenarios(tmp_path: Path) -> None:
    write_demo_package(tmp_path, load_config())
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert len(manifest["sessions"]) == 3
    for scenario in SCENARIOS:
        assert (tmp_path / scenario.session_id / "telemetry.csv").exists()
        assert (tmp_path / scenario.session_id / "events.csv").exists()
        assert (tmp_path / scenario.session_id / "rides.csv").exists()
        assert (tmp_path / scenario.session_id / "summary.json").exists()
