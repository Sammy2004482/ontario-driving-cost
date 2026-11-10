"""Rebuild every result, chart, the Excel model, the notebook and the memo from the processed data.

    python run_all.py              # use data/processed as is
    python run_all.py --fetch      # download fresh data first
"""
import subprocess
import sys
import time

STEPS = [
    ("data", [sys.executable, "-m", "data.fetch_all"]),
    ("tco + excel", [sys.executable, "-m", "drivecost.excel_model"]),
    ("pass-through", [sys.executable, "-m", "drivecost.passthrough"]),
    ("inflation", [sys.executable, "-m", "drivecost.inflation"]),
    ("fuel risk", [sys.executable, "-m", "drivecost.risk"]),
    ("hedge", [sys.executable, "-m", "drivecost.hedge"]),
    ("credit stress", [sys.executable, "-m", "drivecost.credit_stress"]),
    ("insurance pricing (~2 min, ~5 GB RAM)", [sys.executable, "-m", "drivecost.pricing"]),
    ("memo analysis", [sys.executable, "-m", "drivecost.decision"]),
    ("notebook", ["jupyter", "nbconvert", "--to", "notebook", "--execute", "--inplace",
                  "notebooks/03_passthrough_inflation.ipynb"]),
    ("memo pdf", [sys.executable, "memo/build_memo.py"]),
]

if __name__ == "__main__":
    for name, cmd in STEPS:
        if name == "data" and "--fetch" not in sys.argv:
            continue
        t = time.time()
        print(f"== {name}", flush=True)
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL if name != "memo pdf" else None)
        print(f"   done in {time.time() - t:.0f}s", flush=True)
