#!/usr/bin/env python3
"""Run a 360 ERP encode sweep and delete reconstruction YUV after metrics.

For each QP, the script encodes anchor/proposed, computes WS-PSNR, optional
S-PSNR-NN, and CPP-PSNR from the generated reconstruction files, then deletes
the reconstruction files immediately.  Bitstreams, logs, CSV and JSON metrics
are kept.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import time
from pathlib import Path

try:
    from lard_360_metrics import (
        bdrate,
        compute_case_with_bitdepth,
        erp_spsnr_nn_indices,
        parse_log,
    )
except ModuleNotFoundError:
    from tools.lard_360_metrics import (
        bdrate,
        compute_case_with_bitdepth,
        erp_spsnr_nn_indices,
        parse_log,
    )


def build_bdrate_metrics(rows: list[dict[str, float | int | str]]) -> dict[str, float]:
    rates_a = [float(r["AnchorKbps"]) for r in rows]
    rates_p = [float(r["ProposedKbps"]) for r in rows]
    metrics_out: dict[str, float] = {}
    for metric in ("ORD", "WS", "S", "CPP"):
        for comp in ("Y", "U", "V", "YUV"):
            key = f"{metric}_{comp}"
            metrics_out[f"{key}_BDBR_pct"] = bdrate(
                rates_a,
                [float(r[f"Anchor_{key}"]) for r in rows],
                rates_p,
                [float(r[f"Proposed_{key}"]) for r in rows],
            )
    return metrics_out


def run(cmd: list[str], log_path: Path) -> float:
    start = time.perf_counter()
    with log_path.open("w", encoding="utf-16") as log:
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, text=True)
    elapsed = time.perf_counter() - start
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")
    return elapsed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--encoder", type=Path, default=Path(r"I:\vvenc-LFNST\bin\release-static\vvencFFapp.exe"))
    ap.add_argument("--orig", type=Path, required=True)
    ap.add_argument("--width", type=int, required=True)
    ap.add_argument("--height", type=int, required=True)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--input-chroma-format", default="420")
    ap.add_argument("--orig-bitdepth", type=int, default=8)
    ap.add_argument("--rec-bitdepth", type=int, default=10)
    ap.add_argument("--sphere-file", type=Path, required=True)
    ap.add_argument("--out-root", type=Path, required=True)
    ap.add_argument("--qps", default="22,27,32,37")
    ap.add_argument("--frames", type=int, default=1)
    ap.add_argument("--threads", type=int, default=20)
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--anchor-additional", default="LardLfnstSkip=0")
    ap.add_argument("--proposed-additional", default="LardLfnstSkip=8")
    ap.add_argument("--keep-rec", action="store_true")
    args = ap.parse_args()

    qps = [int(x) for x in args.qps.split(",") if x]
    args.out_root.mkdir(parents=True, exist_ok=True)

    spsnr_table = erp_spsnr_nn_indices(args.sphere_file, args.width, args.height)

    rows: list[dict[str, float | int | str]] = []
    summary_rows: list[dict[str, float | int | str]] = []

    for qp in qps:
        case_dir = args.out_root / f"AerialCity_QP{qp}"
        case_dir.mkdir(parents=True, exist_ok=True)
        case_metrics: dict[str, dict[str, float]] = {}
        case_times: dict[str, float] = {}

        for kind, additional in (("anchor", args.anchor_additional), ("proposed", args.proposed_additional)):
            additional = additional.replace("{qp}", str(qp))
            vvc = case_dir / f"{kind}.vvc"
            rec = case_dir / f"{kind}_rec.yuv"
            log = case_dir / f"{kind}.log"
            for p in (vvc, rec, log):
                if p.exists():
                    p.unlink()
            cmd = [
                str(args.encoder),
                "--preset", args.preset,
                "-i", str(args.orig),
                "-s", f"{args.width}x{args.height}",
                "-r", str(args.fps),
                "--InputChromaFormat", args.input_chroma_format,
                "-q", str(qp),
                "--qpa", "0",
                "-f", str(args.frames),
                "-ip", "1",
                "--mtprofile", "0",
                "--threads", str(args.threads),
                "--additional", additional,
                "-b", str(vvc),
                "-o", str(rec),
            ]
            wall = run(cmd, log)
            bitrate, ord_y, ord_u, ord_v, ord_yuv = parse_log(log)
            metrics = compute_case_with_bitdepth(
                args.orig, rec, args.width, args.height, args.rec_bitdepth, args.orig_bitdepth,
                spsnr_table, frames=args.frames
            )
            metrics["ORD_Y"] = ord_y
            metrics["ORD_U"] = ord_u
            metrics["ORD_V"] = ord_v
            metrics["ORD_YUV"] = ord_yuv
            metrics["Kbps"] = bitrate
            metrics["Bytes"] = float(vvc.stat().st_size)
            metrics["WallSeconds"] = wall
            case_metrics[kind] = metrics
            case_times[kind] = wall
            if not args.keep_rec and rec.exists():
                rec.unlink()

        row: dict[str, float | int | str] = {"QP": qp}
        row["AnchorKbps"] = case_metrics["anchor"]["Kbps"]
        row["ProposedKbps"] = case_metrics["proposed"]["Kbps"]
        for key, value in case_metrics["anchor"].items():
            row[f"Anchor_{key}"] = value
        for key, value in case_metrics["proposed"].items():
            row[f"Proposed_{key}"] = value
        rows.append(row)
        summary_rows.append(
            {
                "QP": qp,
                "AnchorSeconds": case_times["anchor"],
                "ProposedSeconds": case_times["proposed"],
                "AnchorBytes": int(case_metrics["anchor"]["Bytes"]),
                "ProposedBytes": int(case_metrics["proposed"]["Bytes"]),
            }
        )

        with (args.out_root / "metric_curve.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        with (args.out_root / "run_summary.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(summary_rows[0].keys()))
            writer.writeheader()
            writer.writerows(summary_rows)

    metrics_out = build_bdrate_metrics(rows)

    anchor_time = sum(float(r["AnchorSeconds"]) for r in summary_rows)
    proposed_time = sum(float(r["ProposedSeconds"]) for r in summary_rows)
    anchor_bytes = sum(int(r["AnchorBytes"]) for r in summary_rows)
    proposed_bytes = sum(int(r["ProposedBytes"]) for r in summary_rows)
    metrics_out["TS_pct"] = (anchor_time - proposed_time) / anchor_time * 100.0
    metrics_out["AnchorTime_sec"] = anchor_time
    metrics_out["ProposedTime_sec"] = proposed_time
    metrics_out["ByteDelta_pct"] = (proposed_bytes - anchor_bytes) / anchor_bytes * 100.0

    (args.out_root / "metrics.json").write_text(json.dumps(metrics_out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics_out, indent=2))


if __name__ == "__main__":
    main()
