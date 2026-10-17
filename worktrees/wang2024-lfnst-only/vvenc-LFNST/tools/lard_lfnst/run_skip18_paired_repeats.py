#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

from tools.lard_360_metrics import (
    bdrate,
    compute_case_with_bitdepth,
    erp_spsnr_nn_indices,
    parse_log,
    read_yuv420_frame,
)


ANCHOR_ADDITIONAL = "LFNST=1 LardLfnstSkip=0"
def proposed_additional(target_profile: int) -> str:
    return (
        "LFNST=1 LardLfnstSkip=18 LardLfnst18RealSkip=1 "
        "LardLfnst18HighCostOnly=0 LardLfnst18OptLevel=4 "
        f"LardLfnst18TargetProfile={target_profile}"
    )


def resolve_additional(kind: str, args: argparse.Namespace) -> str:
    if kind == "anchor":
        return args.anchor_additional or ANCHOR_ADDITIONAL
    return args.proposed_additional or proposed_additional(args.target_profile)


def build_interleaved_schedule(repeats: int) -> list[tuple[int, str]]:
    schedule: list[tuple[int, str]] = []
    for repeat in range(1, repeats + 1):
        order = ("anchor", "proposed") if repeat % 2 else ("proposed", "anchor")
        schedule.extend((repeat, kind) for kind in order)
    return schedule


def _ts(anchor: float, proposed: float) -> float:
    return (anchor - proposed) / anchor * 100.0


def _stats(values: list[float]) -> dict[str, float]:
    return {
        "mean_TS_pct": statistics.fmean(values),
        "median_TS_pct": statistics.median(values),
        "std_TS_pct": statistics.pstdev(values),
        "min_TS_pct": min(values),
        "max_TS_pct": max(values),
    }


def summarize_paired_times(rows: list[dict[str, Any]]) -> dict[str, Any]:
    indexed = {
        (int(row["repeat"]), int(row["QP"]), str(row["kind"])): float(row["Seconds"])
        for row in rows
    }
    repeats = sorted({key[0] for key in indexed})
    qps = sorted({key[1] for key in indexed})

    repeat_rows: list[dict[str, float | int]] = []
    for repeat in repeats:
        anchor = sum(indexed[(repeat, qp, "anchor")] for qp in qps)
        proposed = sum(indexed[(repeat, qp, "proposed")] for qp in qps)
        repeat_rows.append(
            {
                "repeat": repeat,
                "AnchorSeconds": anchor,
                "ProposedSeconds": proposed,
                "TS_pct": _ts(anchor, proposed),
            }
        )

    by_qp: dict[str, dict[str, float | int | list[float]]] = {}
    for qp in qps:
        values = [
            _ts(indexed[(repeat, qp, "anchor")], indexed[(repeat, qp, "proposed")])
            for repeat in repeats
        ]
        by_qp[str(qp)] = {
            **_stats(values),
            "positive_pairs": sum(value > 0.0 for value in values),
            "pairs": len(values),
            "paired_TS_pct": values,
        }

    repeat_values = [float(row["TS_pct"]) for row in repeat_rows]
    return {
        "repeats": repeat_rows,
        "overall": {
            **_stats(repeat_values),
            "positive_repeats": sum(value > 0.0 for value in repeat_values),
            "repeats": len(repeat_values),
        },
        "by_qp": by_qp,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_encode(
    encoder: Path,
    orig: Path,
    out_dir: Path,
    qp: int,
    repeat: int,
    kind: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    run_dir = out_dir / f"QP{qp}" / f"repeat{repeat}"
    run_dir.mkdir(parents=True, exist_ok=True)
    bitstream = run_dir / f"{kind}.vvc"
    rec = run_dir / f"{kind}_rec.yuv"
    log = run_dir / f"{kind}.log"
    for path in (bitstream, rec, log):
        path.unlink(missing_ok=True)

    additional = resolve_additional(kind, args)
    cmd = [
        str(encoder),
        "--preset",
        args.preset,
        "-i",
        str(orig),
        "-s",
        f"{args.width}x{args.height}",
        "-r",
        str(args.fps),
        "--InputChromaFormat",
        "420",
        "-q",
        str(qp),
        "--qpa",
        "0",
        "-f",
        str(args.frames),
        "-ip",
        "1",
        "--mtprofile",
        "0",
        "--threads",
        str(args.threads),
        "--additional",
        additional,
        "-b",
        str(bitstream),
        "-o",
        str(rec),
    ]
    started = time.perf_counter()
    with log.open("w", encoding="utf-16") as handle:
        proc = subprocess.run(cmd, stdout=handle, stderr=subprocess.STDOUT, text=True)
    seconds = time.perf_counter() - started
    if proc.returncode != 0:
        raise RuntimeError(f"encode failed ({proc.returncode}): {' '.join(cmd)}")

    bitrate, ord_y, ord_u, ord_v, ord_yuv = parse_log(log)
    row: dict[str, Any] = {
        "repeat": repeat,
        "QP": qp,
        "kind": kind,
        "Seconds": seconds,
        "Kbps": bitrate,
        "Bytes": bitstream.stat().st_size,
        "SHA256": _sha256(bitstream),
        "ORD_Y": ord_y,
        "ORD_U": ord_u,
        "ORD_V": ord_v,
        "ORD_YUV": ord_yuv,
    }
    try:
        if repeat == 1:
            row.update(
                compute_case_with_bitdepth(
                    args.orig_frame,
                    rec,
                    args.width,
                    args.height,
                    args.rec_bitdepth,
                    args.orig_bitdepth,
                    args.spsnr_table,
                )
            )
    finally:
        rec.unlink(missing_ok=True)

    if repeat > 1 and not args.keep_all_bitstreams:
        bitstream.unlink(missing_ok=True)
    return row


def _bd_metrics(rows: list[dict[str, Any]], qps: list[int]) -> dict[str, float]:
    first = {
        (int(row["QP"]), str(row["kind"])): row
        for row in rows
        if int(row["repeat"]) == 1
    }
    rates_anchor = [float(first[(qp, "anchor")]["Kbps"]) for qp in qps]
    rates_proposed = [float(first[(qp, "proposed")]["Kbps"]) for qp in qps]
    result: dict[str, float] = {}
    for metric in ("ORD", "WS", "S", "CPP"):
        for comp in ("Y", "U", "V", "YUV"):
            key = f"{metric}_{comp}"
            result[f"{key}_BDBR_pct"] = bdrate(
                rates_anchor,
                [float(first[(qp, "anchor")][key]) for qp in qps],
                rates_proposed,
                [float(first[(qp, "proposed")][key]) for qp in qps],
            )
    anchor_bytes = sum(int(first[(qp, "anchor")]["Bytes"]) for qp in qps)
    proposed_bytes = sum(int(first[(qp, "proposed")]["Bytes"]) for qp in qps)
    result["ByteDelta_pct"] = (proposed_bytes - anchor_bytes) / anchor_bytes * 100.0
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--encoder", type=Path, required=True)
    parser.add_argument("--orig", type=Path, required=True)
    parser.add_argument("--sphere-file", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--qps", default="22,27,32,37")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--width", type=int, default=3840)
    parser.add_argument("--height", type=int, default=1920)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--frames", type=int, default=4)
    parser.add_argument("--threads", type=int, default=20)
    parser.add_argument("--preset", default="medium")
    parser.add_argument("--orig-bitdepth", type=int, default=8)
    parser.add_argument("--rec-bitdepth", type=int, default=10)
    parser.add_argument("--keep-all-bitstreams", action="store_true")
    parser.add_argument("--target-profile", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--anchor-additional", default="")
    parser.add_argument("--proposed-additional", default="")
    args = parser.parse_args()

    if args.repeats < 1:
        raise ValueError("--repeats must be positive")
    args.out_root.mkdir(parents=True, exist_ok=True)
    qps = [int(value) for value in args.qps.split(",") if value]
    args.orig_frame = read_yuv420_frame(
        args.orig, args.width, args.height, bitdepth=args.orig_bitdepth
    )
    args.spsnr_table = erp_spsnr_nn_indices(
        args.sphere_file, args.width, args.height
    )

    rows: list[dict[str, Any]] = []
    schedule = build_interleaved_schedule(args.repeats)
    for qp in qps:
        for repeat, kind in schedule:
            row = _run_encode(
                args.encoder, args.orig, args.out_root, qp, repeat, kind, args
            )
            rows.append(row)
            _write_csv(args.out_root / "raw_runs.csv", rows)
            print(
                f"QP={qp} repeat={repeat} kind={kind} seconds={row['Seconds']:.6f}",
                flush=True,
            )

    paired = summarize_paired_times(rows)
    _write_csv(args.out_root / "paired_repeats.csv", paired["repeats"])
    qp_rows = [
        {"QP": int(qp), **values}
        for qp, values in paired["by_qp"].items()
    ]
    _write_csv(args.out_root / "paired_by_qp.csv", qp_rows)

    bitexact: list[dict[str, Any]] = []
    for qp in qps:
        for kind in ("anchor", "proposed"):
            hashes = {
                str(row["SHA256"])
                for row in rows
                if int(row["QP"]) == qp and str(row["kind"]) == kind
            }
            bitexact.append(
                {
                    "QP": qp,
                    "kind": kind,
                    "unique_hashes": len(hashes),
                    "stable": len(hashes) == 1,
                }
            )
    _write_csv(args.out_root / "hash_stability.csv", bitexact)

    result = {
        "configuration": {
            "anchor": resolve_additional("anchor", args),
            "proposed": resolve_additional("proposed", args),
            "target_profile": args.target_profile,
            "frames": args.frames,
            "threads": args.threads,
            "preset": args.preset,
            "repeats": args.repeats,
            "schedule": schedule,
        },
        "paired_timing": paired,
        "metrics": _bd_metrics(rows, qps),
        "hash_stability": bitexact,
    }
    (args.out_root / "summary.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )

    remaining_yuv = list(args.out_root.rglob("*.yuv"))
    if remaining_yuv:
        raise RuntimeError(f"reconstruction YUV files remain: {remaining_yuv[:3]}")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
