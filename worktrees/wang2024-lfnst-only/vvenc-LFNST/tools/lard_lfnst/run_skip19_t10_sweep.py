#!/usr/bin/env python3
"""Run or summarize the four Skip19 T10 experiment profiles."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


YUV_BDBR_KEYS = (
    "ORD_YUV_BDBR_pct",
    "WS_YUV_BDBR_pct",
    "S_YUV_BDBR_pct",
    "CPP_YUV_BDBR_pct",
)


def profile_additional_args() -> dict[str, str]:
    return {
        "T10-0": "LFNST=1 LardLfnstSkip=19 LardLfnst19Profile=0",
        "T10-1": (
            "LFNST=1 LardLfnstSkip=19 LardLfnst19Profile=1 "
            "LardLfnst19SingleMargin=1.0"
        ),
        "T10-2": (
            "LFNST=1 LardLfnstSkip=19 LardLfnst19Profile=2 "
            "LardLfnst19SingleMargin=0.25"
        ),
        "T10-3": (
            "LFNST=1 LardLfnstSkip=19 LardLfnst19Profile=3 "
            "LardLfnst19SingleMargin=0.25 LardLfnst19ZeroMargin=0.0"
        ),
    }


def max_yuv_bdr(metrics: dict[str, float]) -> float:
    return max(float(metrics[key]) for key in YUV_BDBR_KEYS)


def select_best_feasible(results: dict[str, dict[str, float]], limit: float) -> str | None:
    feasible = [
        (float(metrics["TS_pct"]), name)
        for name, metrics in results.items()
        if max_yuv_bdr(metrics) <= limit
    ]
    return max(feasible)[1] if feasible else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-script", type=Path, default=Path(__file__).parents[1] / "lard_run_eval_360_cleanup.py")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--common-args", nargs=argparse.REMAINDER)
    ap.add_argument("--out-root", type=Path, required=True)
    ap.add_argument("--limit", type=float, default=0.5)
    args = ap.parse_args()

    args.out_root.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, float]] = {}
    for name, additional in profile_additional_args().items():
        out_dir = args.out_root / name
        cmd = [
            args.python,
            str(args.eval_script),
            "--out-root",
            str(out_dir),
            "--anchor-additional",
            "LFNST=1 LardLfnstSkip=0",
            "--proposed-additional",
            additional,
        ] + (args.common_args or [])
        subprocess.run(cmd, check=True)
        results[name] = json.loads((out_dir / "metrics.json").read_text(encoding="utf-8"))

    report = {
        "constraint_pct": args.limit,
        "best_feasible": select_best_feasible(results, args.limit),
        "profiles": results,
    }
    (args.out_root / "t10_summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
