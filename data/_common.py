"""Shared helpers for the download scripts.

Design rules (so that re-running gives identical files):
* every processed CSV is sorted and written with a fixed float format;
* the pull date is NOT written into the data files, it goes to
  data/processed/pull_log.json together with the source URL, row count
  and a SHA-256 of the file;
* raw downloads are cached in data/raw/ (git-ignored); pass --refresh to
  any script to download them again.
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import io
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
PROCESSED = ROOT / "processed"
PULL_LOG = PROCESSED / "pull_log.json"

START_MONTH = "2014-01"  # one year before 2015 so lags and y/y changes exist from 2015
HEADERS = {"User-Agent": "ontario-driving-cost/1.0 (student research project)"}

RAW.mkdir(exist_ok=True)
PROCESSED.mkdir(exist_ok=True)


def refresh_requested() -> bool:
    return "--refresh" in sys.argv


def download(url: str, name: str, refresh: bool | None = None, timeout: int = 600) -> Path:
    """Download url to data/raw/name unless it is already cached."""
    refresh = refresh_requested() if refresh is None else refresh
    path = RAW / name
    if path.exists() and not refresh:
        return path
    for attempt in range(4):
        try:
            with requests.get(url, headers=HEADERS, timeout=(30, timeout), stream=True) as r:
                r.raise_for_status()
                tmp = path.with_suffix(path.suffix + ".part")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                tmp.replace(path)
            return path
        except requests.RequestException as exc:  # pragma: no cover - network
            wait = 2 ** (attempt + 1)
            print(f"  download failed ({exc}); retrying in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"could not download {url}")


def get_json(url: str) -> dict:
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.json()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(df: pd.DataFrame, name: str, source: str | list[str], float_format: str = "%.6g") -> Path:
    """Write a deterministic CSV (or .csv.gz) and record it in the pull log."""
    path = PROCESSED / name
    text = df.to_csv(index=False, float_format=float_format, lineterminator="\n")
    if name.endswith(".gz"):
        buf = io.BytesIO()
        # mtime=0 and no filename so the gzip bytes are identical on every run
        with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0) as gz:
            gz.write(text.encode())
        path.write_bytes(buf.getvalue())
    else:
        path.write_text(text)
    log = json.loads(PULL_LOG.read_text()) if PULL_LOG.exists() else {}
    log[name] = {
        "source": source,
        "pulled_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rows": int(len(df)),
        "first": str(df.iloc[0, 0]) if len(df) else None,
        "last": str(df.iloc[-1, 0]) if len(df) else None,
        "sha256": _sha256(path),
    }
    PULL_LOG.write_text(json.dumps(dict(sorted(log.items())), indent=2) + "\n")
    print(f"  wrote {path.relative_to(ROOT.parent)} ({len(df):,} rows)")
    return path


def read_eia_xls(path: Path, value_name: str) -> pd.DataFrame:
    """EIA 'hist_xls' files: sheet 'Data 1', two header rows, then Date | value."""
    d = pd.read_excel(path, sheet_name="Data 1", skiprows=2)
    d.columns = ["date", value_name]
    d["date"] = pd.to_datetime(d["date"])
    return d.dropna()
