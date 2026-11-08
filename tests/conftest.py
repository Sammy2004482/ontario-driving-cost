import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

needs_data = pytest.mark.skipif(not (ROOT / "data" / "processed" / "gas_prices_monthly.csv").exists(),
                                reason="run python -m data.fetch_all first")
