from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from jarred_drive.config import load_config
from jarred_drive.synthetic import write_demo_package


def test_every_dashboard_page_runs_without_exception() -> None:
    demo_root = Path("data/demo")
    if not (demo_root / "manifest.json").exists():
        write_demo_package(demo_root, load_config())
    script = Path(__file__).resolve().parents[1] / "src/jarred_drive/dashboard/app.py"
    app = AppTest.from_file(script, default_timeout=30)
    app.run()
    assert not app.exception
    assert app.title[0].value == "Flight Deck"
    for page in ("Rides", "Equipment", "Tuning", "Progress", "Annotate", "Raw Data"):
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, page
        assert app.title[0].value == page
