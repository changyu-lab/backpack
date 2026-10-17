#!/usr/bin/env python3
"""Aggregate updated LARD-LFNST candidate traces into quantized-ROI block rows.

The trace CSV must contain nonZero, lastPos and roiQ00..roiQ47.  Features are
read from the no-LFNST/DCT2 row (lfnstIdx=0,mtsIdx=0), while j0/j1/j2 labels
are the best observed cost for each LFNST index over all transform modes.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


ROI_COLS = [f"roiQ{i:02d}" for i in range(48)]


def ff(row: dict[str, str], key: str, default: float = math.nan) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def ii(row: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(row.get(key, default)))
    except (TypeError, ValueError):
        return default


def valid_cost(x: float) -> bool:
    return math.isfinite(x) and abs(x) < 1.0e100


def corr_proxy(roi: list[float]) -> float:
    energy = sum(x * x for x in roi)
    if energy <= 0.0:
        return 0.0
    pair = sum(abs(roi[i] * roi[i + 1]) for i in range(len(roi) - 1))
    return pair / (energy + 1.0e-9)


def new_state(row: dict[str, str]) -> dict[str, object]:
    return {
        "poc": ii(row, "poc"),
        "x": ii(row, "x"),
        "y": ii(row, "y"),
        "w": ii(row, "w"),
        "h": ii(row, "h"),
        "qp": ii(row, "qp"),
        "intraMode": ii(row, "intraMode"),
        "absLatDeg": ff(row, "absLatDeg"),
        "thetaMaxDeg": ff(row, "thetaMaxDeg"),
        "roiEnergyQ": math.nan,
        "lfRatio": math.nan,
        "predNz": math.nan,
        "n0dct2": -1,
        "last0dct2": -1,
        "roiDim": -1,
        "corrProxy": math.nan,
        "roiAbsSum": math.nan,
        "roiEnergyQActual": math.nan,
        "j": [math.inf, math.inf, math.inf],
        "bestMts": [-1, -1, -1],
        "n": [-1, -1, -1],
        "last": [-1, -1, -1],
        "fracBits": [math.nan, math.nan, math.nan],
        "dist": [math.nan, math.nan, math.nan],
    }


def update_state(st: dict[str, object], row: dict[str, str]) -> None:
    idx = ii(row, "lfnstIdx", -1)
    if idx < 0 or idx > 2:
        return

    mts = ii(row, "mtsIdx", -1)
    cost = ff(row, "cost")
    if valid_cost(cost) and cost < st["j"][idx]:  # type: ignore[index]
        st["j"][idx] = cost  # type: ignore[index]
        st["bestMts"][idx] = mts  # type: ignore[index]
        st["n"][idx] = ii(row, "nonZero", ii(row, "numSig", -1))  # type: ignore[index]
        st["last"][idx] = ii(row, "lastPos", -1)  # type: ignore[index]
        st["fracBits"][idx] = ff(row, "fracBits")  # type: ignore[index]
        st["dist"][idx] = ff(row, "dist")  # type: ignore[index]

    if idx == 0 and mts == 0:
        roi = [ff(row, c, 0.0) for c in ROI_COLS]
        dim = ii(row, "roiDim", 48)
        if dim <= 0 or dim > 48:
            dim = 48
        roi = roi[:dim]
        st["roiEnergyQ"] = ff(row, "roiEnergyQ")
        st["lfRatio"] = ff(row, "lfRatio")
        st["predNz"] = ff(row, "predNz")
        st["n0dct2"] = ii(row, "nonZero", ii(row, "numSig", -1))
        st["last0dct2"] = ii(row, "lastPos", -1)
        st["roiDim"] = dim
        st["corrProxy"] = corr_proxy(roi)
        st["roiAbsSum"] = sum(abs(x) for x in roi)
        st["roiEnergyQActual"] = sum(x * x for x in roi) / max(1, dim)


def finish_state(st: dict[str, object]) -> dict[str, object] | None:
    j = st["j"]  # type: ignore[assignment]
    if not valid_cost(j[0]) or not valid_cost(j[1]) or not valid_cost(j[2]):
        return None
    if int(st["n0dct2"]) < 0 or int(st["last0dct2"]) < 0:
        return None
    best_idx = min(range(3), key=lambda k: j[k])
    best_cost = j[best_idx]
    out = {
        "poc": st["poc"],
        "x": st["x"],
        "y": st["y"],
        "w": st["w"],
        "h": st["h"],
        "qp": st["qp"],
        "intraMode": st["intraMode"],
        "absLatDeg": st["absLatDeg"],
        "thetaMaxDeg": st["thetaMaxDeg"],
        "roiEnergyQ": st["roiEnergyQ"],
        "lfRatio": st["lfRatio"],
        "predNz": st["predNz"],
        "n0dct2": st["n0dct2"],
        "last0dct2": st["last0dct2"],
        "roiDim": st["roiDim"],
        "corrProxy": st["corrProxy"],
        "roiAbsSum": st["roiAbsSum"],
        "roiEnergyQActual": st["roiEnergyQActual"],
        "j0": j[0],
        "j1": j[1],
        "j2": j[2],
        "bestIdx": best_idx,
        "bestCost": best_cost,
        "g1": (j[0] - j[1]) / max(abs(j[0]), 1.0),
        "g2": (j[0] - j[2]) / max(abs(j[0]), 1.0),
    }
    for idx in range(3):
        out[f"bestMts{idx}"] = st["bestMts"][idx]  # type: ignore[index]
        out[f"n{idx}"] = st["n"][idx]  # type: ignore[index]
        out[f"last{idx}"] = st["last"][idx]  # type: ignore[index]
        out[f"fracBits{idx}"] = st["fracBits"][idx]  # type: ignore[index]
        out[f"dist{idx}"] = st["dist"][idx]  # type: ignore[index]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("trace_csv", nargs="+", type=Path)
    ap.add_argument("--block-csv", type=Path, required=True)
    ap.add_argument("--json-out", type=Path)
    args = ap.parse_args()

    fields = [
        "poc", "x", "y", "w", "h", "qp", "intraMode", "absLatDeg", "thetaMaxDeg",
        "roiEnergyQ", "lfRatio", "predNz", "n0dct2", "last0dct2", "roiDim",
        "corrProxy", "roiAbsSum", "roiEnergyQActual", "j0", "j1", "j2",
        "bestIdx", "bestCost", "g1", "g2", "bestMts0", "n0", "last0",
        "fracBits0", "dist0", "bestMts1", "n1", "last1", "fracBits1", "dist1",
        "bestMts2", "n2", "last2", "fracBits2", "dist2",
    ]

    total_rows = 0
    out_rows = 0
    dropped = 0
    states: dict[tuple[int, int, int, int, int, int, int], dict[str, object]] = {}

    with args.block_csv.open("w", newline="", encoding="utf-8") as out_fh:
        writer = csv.DictWriter(out_fh, fieldnames=fields)
        writer.writeheader()
        for path in args.trace_csv:
            with path.open(newline="", encoding="utf-8", errors="ignore") as fh:
                reader = csv.DictReader(fh)
                missing = [c for c in ["nonZero", "lastPos", "roiDim", *ROI_COLS] if c not in (reader.fieldnames or [])]
                if missing:
                    raise RuntimeError(f"{path} is not an updated trace; missing {missing[:5]}")
                for row in reader:
                    total_rows += 1
                    key = (
                        ii(row, "poc"), ii(row, "x"), ii(row, "y"), ii(row, "w"),
                        ii(row, "h"), ii(row, "qp"), ii(row, "intraMode"),
                    )
                    st = states.get(key)
                    if st is None:
                        st = new_state(row)
                        states[key] = st
                    update_state(st, row)

            for key in list(states):
                row = finish_state(states.pop(key))
                if row is None:
                    dropped += 1
                    continue
                writer.writerow(row)
                out_rows += 1

    summary = {
        "traceFiles": len(args.trace_csv),
        "candidateRows": total_rows,
        "blockRows": out_rows,
        "droppedGroups": dropped,
        "blockCsv": str(args.block_csv),
    }
    if args.json_out:
        args.json_out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
