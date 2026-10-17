#!/usr/bin/env python3
"""Evaluate grouped LARD-LFNST thresholds on block summaries."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


def f(row: dict[str, str], key: str, default: float = math.nan) -> float:
    try:
        return float(row.get(key, default))
    except Exception:
        return default


def i(row: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(row.get(key, default)))
    except Exception:
        return default


def b(row: dict[str, str], key: str) -> bool:
    return str(row.get(key, "")).lower() in {"1", "true", "yes"}


def mode_group(mode: int) -> str:
    if mode == 0:
        return "planar"
    if mode == 1:
        return "dc"
    if mode <= 17:
        return "ang_02_17"
    if mode <= 34:
        return "ang_18_34"
    if mode <= 50:
        return "ang_35_50"
    return "ang_51_66"


def size_group(w: int, h: int) -> str:
    area = w * h
    mn = min(w, h)
    mx = max(w, h)
    if area <= 16:
        return "area_16"
    if area <= 32:
        return "area_32"
    if area <= 64:
        return "area_64"
    if area <= 256:
        return "area_256"
    if area <= 1024:
        return "area_1024"
    if mx >= 4 * mn:
        return "area_large_elong"
    return "area_large"


def load_params(path: Path) -> dict[tuple[int, str, str], dict[str, float]]:
    out = {}
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            out[(i(row, "qp"), row["sizeGroup"], row["modeGroup"])] = {
                "T_E": f(row, "T_E"),
                "T_LF": f(row, "T_LF"),
                "T_N": f(row, "T_N"),
            }
    return out


def nearest_param(params: dict[tuple[int, str, str], dict[str, float]], qp: int, sg: str, mg: str) -> dict[str, float] | None:
    best = None
    best_dist = 999
    for (p_qp, p_sg, p_mg), val in params.items():
        if p_sg != sg or p_mg != mg:
            continue
        dist = abs(p_qp - qp)
        if dist < best_dist:
            best = val
            best_dist = dist
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--params", type=Path, required=True)
    ap.add_argument("--theta-min-deg", type=float, default=None)
    ap.add_argument("--json-out", type=Path)
    ap.add_argument("block_csv", nargs="+", type=Path)
    args = ap.parse_args()

    params = load_params(args.params)
    total = eligible = oracle_keep = pred = false = no_param = 0
    missed_sum = 0.0
    by_file = []

    for path in args.block_csv:
        ft = fe = fok = fp = ff = fnp = 0
        fmiss = 0.0
        with path.open(newline="") as fh:
            for row in csv.DictReader(fh):
                total += 1
                ft += 1
                if not b(row, "hasLfnst"):
                    continue
                eligible += 1
                fe += 1
                if not b(row, "oracleSkip"):
                    oracle_keep += 1
                    fok += 1
                sg = size_group(i(row, "w"), i(row, "h"))
                mg = mode_group(i(row, "intraMode"))
                par = nearest_param(params, i(row, "qp"), sg, mg)
                if par is None:
                    no_param += 1
                    fnp += 1
                    continue
                if args.theta_min_deg is None:
                    stage1 = str(row.get("stage1", "0")) in {"1", "True", "true"}
                else:
                    stage1 = f(row, "thetaMaxDeg") >= args.theta_min_deg
                p = stage1 and f(row, "roiEnergyQ") < par["T_E"] and f(row, "lfRatio") > par["T_LF"] and f(row, "predNz") < par["T_N"]
                if p:
                    pred += 1
                    fp += 1
                    if not b(row, "oracleSkip"):
                        false += 1
                        ff += 1
                        loss = max(0.0, f(row, "missedGain", 0.0))
                        missed_sum += loss
                        fmiss += loss
        by_file.append({"file": str(path), "rows": ft, "eligible": fe, "oracleKeep": fok, "predSkip": fp, "falseSkip": ff, "noParam": fnp, "falseSkipRatePred": ff / fp if fp else 0.0})

    result = {
        "rows": total,
        "eligible": eligible,
        "oracleKeep": oracle_keep,
        "predSkip": pred,
        "falseSkip": false,
        "noParam": no_param,
        "skipRatioEligible": pred / eligible if eligible else 0.0,
        "falseSkipRatePred": false / pred if pred else 0.0,
        "falseSkipRateOracleKeep": false / oracle_keep if oracle_keep else 0.0,
        "meanMissedGain": missed_sum / false if false else 0.0,
        "byFile": by_file,
    }
    text = json.dumps(result, indent=2)
    print(text)
    if args.json_out:
        args.json_out.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
