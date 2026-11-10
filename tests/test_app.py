from pathlib import Path

import pytest

from tests.conftest import needs_data

APP = Path(__file__).resolve().parents[1] / "app.py"


@needs_data
def test_streamlit_app_runs():
    testing = pytest.importorskip("streamlit.testing.v1")
    at = testing.AppTest.from_file(str(APP), default_timeout=120).run()
    assert not at.exception
    assert "Corolla Hybrid" in at.success[0].value
    at.tabs[1].radio[0].set_value("random_walk").run()
    assert not at.exception
