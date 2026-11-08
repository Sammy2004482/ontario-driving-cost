"""freMTPL2 French motor third-party liability data (OpenML 41214 and 41215).

freMTPL2freq: one row per policy (exposure, claim count, rating factors).
freMTPL2sev : one row per claim (policy id, claim amount in EUR).
Saved as deterministic gzip CSVs because the frequency file has ~678k rows.

Run from the repo root:  python -m data.fetch_fremtpl [--refresh]
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from data._common import download, write_csv

URLS = {
    "freq": "https://www.openml.org/data/v1/download/20649148/freMTPL2freq.arff",
    "sev": "https://www.openml.org/data/v1/download/20649149/freMTPL2sev.arff",
}


def read_arff(path: Path) -> pd.DataFrame:
    names, lines, in_data = [], [], False
    with open(path, encoding="utf-8") as f:
        for line in f:
            if in_data:
                lines.append(line)
            elif line.lower().startswith("@attribute"):
                names.append(line.split()[1])
            elif line.lower().startswith("@data"):
                in_data = True
    return pd.read_csv(io.StringIO("".join(lines)), names=names, quotechar="'", skipinitialspace=True)


def main() -> None:
    print("freMTPL2 (OpenML)")
    freq = read_arff(download(URLS["freq"], "freMTPL2freq.arff"))
    freq["IDpol"] = freq.IDpol.astype(int)
    freq["ClaimNb"] = freq.ClaimNb.astype(int)
    write_csv(freq.sort_values("IDpol"), "fremtpl2_freq.csv.gz", URLS["freq"], float_format="%.10g")

    sev = read_arff(download(URLS["sev"], "freMTPL2sev.arff"))
    sev["IDpol"] = sev.IDpol.astype(int)
    write_csv(sev.sort_values(["IDpol", "ClaimAmount"]), "fremtpl2_sev.csv.gz", URLS["sev"], float_format="%.10g")


if __name__ == "__main__":
    main()
