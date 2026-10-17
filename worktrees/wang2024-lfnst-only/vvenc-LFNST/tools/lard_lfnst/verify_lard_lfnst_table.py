#!/usr/bin/env python3
"""Validate generated Skip15 covariance table artifacts."""
from __future__ import annotations

import argparse
import csv
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

from generate_lard_lfnst_cov_table import LAT_BINS, SIZES


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--generator", type=Path)
    parser.add_argument("--rom-lfnst", type=Path)
    args = parser.parse_args()

    with args.summary.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    expected = len(LAT_BINS) * len(SIZES) * 2 * 4
    if len(rows) != expected:
        raise SystemExit(f"entry count mismatch: {len(rows)} != {expected}")
    keys = {(r["latBin"], r["W"], r["H"], r["transpose"], r["setIdx"]) for r in rows}
    if len(keys) != expected:
        raise SystemExit("duplicate or missing table keys")
    for row in rows:
        if float(row["minEigX"]) < -1e-8 or float(row["minVarX"]) < -1e-10 or float(row["minVarY"]) < -1e-10:
            raise SystemExit(f"invalid covariance row: {row}")
        tx = float(row["traceX"])
        for key in ("traceY1", "traceY2"):
            ratio = float(row[key]) / max(tx, 1e-12)
            if not 1e-3 <= ratio <= 1e3:
                raise SystemExit(f"abnormal energy ratio {ratio}: {row}")

    if args.generator and args.rom_lfnst:
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            for out in (a, b):
                subprocess.run(
                    [sys.executable, str(args.generator), "--rom-lfnst", str(args.rom_lfnst), "--out-dir", out],
                    check=True,
                )
            for name in ("LardLfnstCovTable.h", "LardLfnstCovTable.cpp", "lard_lfnst_cov_summary.csv"):
                ha = hashlib.sha256((Path(a) / name).read_bytes()).hexdigest()
                hb = hashlib.sha256((Path(b) / name).read_bytes()).hexdigest()
                if ha != hb:
                    raise SystemExit(f"non-deterministic output: {name}")
    print(f"verified {expected} covariance entries")


if __name__ == "__main__":
    main()
