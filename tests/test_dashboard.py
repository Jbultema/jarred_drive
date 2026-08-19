from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from jarred_drive.config import load_config
from jarred_drive.synthetic import SCENARIOS, write_demo_package


def test_every_dashboard_page_runs_without_exception() -> None:
    demo_root = Path("data/demo")
    if not (demo_root / "manifest.json").exists():
        write_demo_package(demo_root, load_config())
    script = Path(__file__).resolve().parents[1] / "src/jarred_drive/dashboard/app.py"
    app = AppTest.from_file(script, default_timeout=30)
    app.run()
    assert not app.exception
    assert app.title[0].value == "Devices / Sync"
    pages = (
        "Devices / Sync",
        "Flight Deck",
        "Launch Lab",
        "Ride Dynamics",
        "Thermal Lab",
        "System Health",
        "Tuning",
        "Progress",
        "Annotate",
        "Raw Data",
    )
    for session_id in [scenario.session_id for scenario in SCENARIOS]:
        app.sidebar.selectbox[0].set_value(session_id).run()
        for page in pages:
            app.sidebar.radio[0].set_value(page).run()
            assert not app.exception, f"{session_id}: {page}"
            assert app.title[0].value == page
