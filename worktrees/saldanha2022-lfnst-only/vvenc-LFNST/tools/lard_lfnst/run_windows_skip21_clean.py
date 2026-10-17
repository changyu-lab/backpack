#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ANCHOR_ADDITIONAL = "LFNST=1 LardLfnstSkip=0"
LFNST_OFF_ADDITIONAL = "LFNST=0"


def skip21_additional(profile: int) -> str:
    return (
        "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=1 "
        f"LardLfnst21Profile={profile}"
    )


def find_aerialcity(sequence_root: Path) -> Path:
    patterns = (
        "AerialCity*3840x1920*420*erp*.yuv",
        "AerialCity*3840x1920*.yuv",
        "AerialCity*.yuv",
    )
    for pattern in patterns:
        matches = sorted(sequence_root.rglob(pattern))
        if matches:
            return matches[0]
    raise FileNotFoundError(f"could not find AerialCity YUV under {sequence_root}")


def run_job(
    name: str,
    args: argparse.Namespace,
    orig: Path,
    frames: int,
    repeats: int,
    target_profile: int,
    proposed_additional: str,
) -> dict[str, Any]:
    out_root = args.out_root / name / "timing"
    cmd = [
        sys.executable,
        "-m",
        "tools.lard_lfnst.run_skip18_paired_repeats",
        "--encoder",
        str(args.encoder),
        "--orig",
        str(orig),
        "--sphere-file",
        str(args.sphere_file),
        "--out-root",
        str(out_root),
        "--qps",
        args.qps,
        "--frames",
        str(frames),
        "--repeats",
        str(repeats),
        "--threads",
        str(args.threads),
        "--preset",
        args.preset,
        "--target-profile",
        str(target_profile),
        "--anchor-additional",
        ANCHOR_ADDITIONAL,
        "--proposed-additional",
        proposed_additional,
    ]
    print(f"=== {name} ===", flush=True)
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)
    return json.loads((out_root / "summary.json").read_text(encoding="utf-8"))


def compact_result(summary: dict[str, Any]) -> dict[str, Any]:
    timing = summary["paired_timing"]["overall"]
    metrics = summary.get("metrics", {})
    return {
        "median_TS_pct": timing["median_TS_pct"],
        "mean_TS_pct": timing["mean_TS_pct"],
        "std_TS_pct": timing["std_TS_pct"],
        "min_TS_pct": timing["min_TS_pct"],
        "max_TS_pct": timing["max_TS_pct"],
        "positive_repeats": timing["positive_repeats"],
        "repeats": timing["repeats"],
        "CPP_Y_BDBR_pct": metrics.get("CPP_Y_BDBR_pct"),
        "WS_Y_BDBR_pct": metrics.get("WS_Y_BDBR_pct"),
        "S_Y_BDBR_pct": metrics.get("S_Y_BDBR_pct"),
        "ORD_Y_BDBR_pct": metrics.get("ORD_Y_BDBR_pct"),
        "CPP_YUV_BDBR_pct": metrics.get("CPP_YUV_BDBR_pct"),
        "ByteDelta_pct": metrics.get("ByteDelta_pct"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run clean Windows Skip21 E5/E10 timing plus an LFNST-off upper-bound "
            "comparison with anchor calibration."
        )
    )
    parser.add_argument(
        "--encoder",
        type=Path,
        default=Path("bin") / "vvencFFapp.exe",
        help="Path to vvencFFapp.exe inside the package.",
    )
    parser.add_argument(
        "--sequence-root",
        type=Path,
        default=Path(r"F:\Sequences360"),
        help="Root containing AerialCity YUV.",
    )
    parser.add_argument(
        "--orig",
        type=Path,
        default=None,
        help="Explicit AerialCity YUV path. Overrides --sequence-root search.",
    )
    parser.add_argument(
        "--sphere-file",
        type=Path,
        default=Path("resources") / "sphere_655362.txt",
    )
    parser.add_argument("--out-root", type=Path, default=Path("runs") / "skip21_clean_windows")
    parser.add_argument("--qps", default="22,27,32,37")
    parser.add_argument("--threads", type=int, default=20)
    parser.add_argument("--preset", default="medium")
    parser.add_argument("--skip-anchor-calibration", action="store_true")
    args = parser.parse_args()

    args.encoder = args.encoder.resolve()
    args.sphere_file = args.sphere_file.resolve()
    args.out_root = args.out_root.resolve()
    orig = args.orig.resolve() if args.orig else find_aerialcity(args.sequence_root)
    if not args.encoder.exists():
        raise FileNotFoundError(args.encoder)
    if not args.sphere_file.exists():
        raise FileNotFoundError(args.sphere_file)

    args.out_root.mkdir(parents=True, exist_ok=True)
    print(f"encoder={args.encoder}", flush=True)
    print(f"orig={orig}", flush=True)
    print(f"sphere_file={args.sphere_file}", flush=True)
    print(f"out_root={args.out_root}", flush=True)

    jobs: dict[str, dict[str, Any]] = {}
    if not args.skip_anchor_calibration:
        jobs["ANCHOR_8f5"] = run_job(
            "ANCHOR_8f5", args, orig, 8, 5, 0, ANCHOR_ADDITIONAL
        )
    jobs["E5_8f5"] = run_job("E5_8f5", args, orig, 8, 5, 0, skip21_additional(0))
    jobs["LFNST_OFF_8f5"] = run_job(
        "LFNST_OFF_8f5", args, orig, 8, 5, 0, LFNST_OFF_ADDITIONAL
    )

    if not args.skip_anchor_calibration:
        jobs["ANCHOR_4f10"] = run_job(
            "ANCHOR_4f10", args, orig, 4, 10, 0, ANCHOR_ADDITIONAL
        )
    jobs["E10_4f10"] = run_job("E10_4f10", args, orig, 4, 10, 2, skip21_additional(2))

    summary = {
        "configuration": {
            "orig": str(orig),
            "encoder": str(args.encoder),
            "sphere_file": str(args.sphere_file),
            "qps": args.qps,
            "threads": args.threads,
            "preset": args.preset,
            "anchor_additional": ANCHOR_ADDITIONAL,
            "lfnst_off_additional": LFNST_OFF_ADDITIONAL,
            "E5_additional": skip21_additional(0),
            "E10_additional": skip21_additional(2),
        },
        "jobs": {name: compact_result(result) for name, result in jobs.items()},
    }
    summary_path = args.out_root / "clean_windows_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
    print(f"summary={summary_path}", flush=True)


if __name__ == "__main__":
    main()
