#!/usr/bin/env python3
"""Grid-search safety thresholds from LARD-LFNST block summaries."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import numpy as np


def f(row: dict[str, str], key: str) -> float:
    try:
        return float(row[key])
    except Exception:
        return math.nan


def b(row: dict[str, str], key: str) -> bool:
    return str(row.get(key, "")).lower() in {"true", "1", "yes"}


def load(paths: list[Path]) -> dict[str, np.ndarray]:
    roi = []
    lf = []
    nz = []
    stage1 = []
    oracle_skip = []
    has_lfnst = []
    missed_gain = []
    rows = 0
    for path in paths:
        with path.open(newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                rows += 1
                roi.append(f(row, "roiEnergyQ"))
                lf.append(f(row, "lfRatio"))
                nz.append(f(row, "predNz"))
                stage1.append(str(row.get("stage1", "0")) in {"1", "True", "true"})
                oracle_skip.append(b(row, "oracleSkip"))
                has_lfnst.append(b(row, "hasLfnst"))
                missed_gain.append(max(0.0, f(row, "missedGain")))
    return {
        "rows": np.array([rows], dtype=np.int64),
        "roi": np.array(roi, dtype=np.float64),
        "lf": np.array(lf, dtype=np.float64),
        "nz": np.array(nz, dtype=np.float64),
        "stage1": np.array(stage1, dtype=bool),
        "oracle_skip": np.array(oracle_skip, dtype=bool),
        "has_lfnst": np.array(has_lfnst, dtype=bool),
        "missed_gain": np.array(missed_gain, dtype=np.float64),
    }


def frange(values: str) -> list[float]:
    return [float(x) for x in values.split(",") if x.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("block_csv", nargs="+", type=Path)
    ap.add_argument("--te", default="0.5,1,2,4,8,16,32,64,128")
    ap.add_argument("--tlf", default="0.50,0.60,0.70,0.78,0.82,0.86,0.90,0.94")
    ap.add_argument("--tn", default="2,4,6,8,10,12,16,24,32")
    ap.add_argument("--max-false-skip-rate", type=float, default=0.01)
    ap.add_argument("--require-stage1", action="store_true")
    ap.add_argument("--json-out", type=Path)
    args = ap.parse_args()

    data = load(args.block_csv)
    eligible_mask = data["has_lfnst"]
    roi = data["roi"][eligible_mask]
    lf = data["lf"][eligible_mask]
    nz = data["nz"][eligible_mask]
    stage1 = data["stage1"][eligible_mask]
    oracle_skip = data["oracle_skip"][eligible_mask]
    missed_gain = data["missed_gain"][eligible_mask]
    oracle_keep_count = int((~oracle_skip).sum())

    best = None
    trials = []
    for te in frange(args.te):
        for tlf in frange(args.tlf):
            for tn in frange(args.tn):
                mask = (roi < te) & (lf > tlf) & (nz < tn)
                if args.require_stage1:
                    mask &= stage1
                false_mask = mask & (~oracle_skip)
                pred_count = int(mask.sum())
                false_count = int(false_mask.sum())
                false_rate = false_count / pred_count if pred_count else 0.0
                keep_false_rate = false_count / oracle_keep_count if oracle_keep_count else 0.0
                eligible_count = int(eligible_mask.sum())
                skip_ratio = pred_count / eligible_count if eligible_count else 0.0
                mean_loss = float(missed_gain[false_mask].mean()) if false_count else 0.0
                trial = {
                    "T_E": te,
                    "T_LF": tlf,
                    "T_N": tn,
                    "predSkip": pred_count,
                    "falseSkip": false_count,
                    "skipRatioEligible": skip_ratio,
                    "falseSkipRatePred": false_rate,
                    "falseSkipRateOracleKeep": keep_false_rate,
                    "meanMissedGain": mean_loss,
                }
                trials.append(trial)
                if false_rate <= args.max_false_skip_rate:
                    if best is None or (trial["skipRatioEligible"], -trial["falseSkip"], -trial["meanMissedGain"]) > (
                        best["skipRatioEligible"],
                        -best["falseSkip"],
                        -best["meanMissedGain"],
                    ):
                        best = trial

    result = {
        "rows": int(data["rows"][0]),
        "eligible": int(eligible_mask.sum()),
        "oracleKeep": oracle_keep_count,
        "constraintMaxFalseSkipRatePred": args.max_false_skip_rate,
        "requireStage1": args.require_stage1,
        "best": best,
        "top10": sorted(
            [t for t in trials if t["falseSkipRatePred"] <= args.max_false_skip_rate],
            key=lambda t: (t["skipRatioEligible"], -t["falseSkip"], -t["meanMissedGain"]),
            reverse=True,
        )[:10],
    }
    text = json.dumps(result, indent=2)
    print(text)
    if args.json_out:
        args.json_out.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
