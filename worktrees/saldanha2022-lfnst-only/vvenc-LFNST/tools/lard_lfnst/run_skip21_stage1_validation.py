#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from tools.lard_lfnst.summarize_skip21_stage1_stats import summarize_stage1_stats


ANCHOR_ADDITIONAL = "LFNST=1 LardLfnstSkip=0"


def skip21_additional(profile: int) -> str:
    return (
        "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=1 "
        f"LardLfnst21Profile={profile}"
    )


def e10_needs_8f_fallback(
    mean_ts: float, median_ts: float, positive_repeats: int
) -> bool:
    return abs(mean_ts - median_ts) > 3.0 or positive_repeats < 7


def _qps_arg(qps: Iterable[int]) -> str:
    return ",".join(str(qp) for qp in qps)


def timing_command(
    encoder: Path,
    orig: Path,
    sphere_file: Path,
    out_root: Path,
    qps: Sequence[int],
    threads: int,
    preset: str,
    profile: int,
    frames: int,
    repeats: int,
) -> List[str]:
    return [
        sys.executable,
        "-m",
        "tools.lard_lfnst.run_skip18_paired_repeats",
        "--encoder",
        str(encoder),
        "--orig",
        str(orig),
        "--sphere-file",
        str(sphere_file),
        "--out-root",
        str(out_root),
        "--qps",
        _qps_arg(qps),
        "--frames",
        str(frames),
        "--repeats",
        str(repeats),
        "--threads",
        str(threads),
        "--preset",
        preset,
        "--target-profile",
        str(profile),
        "--anchor-additional",
        ANCHOR_ADDITIONAL,
        "--proposed-additional",
        skip21_additional(profile),
    ]


def diagnostic_command(
    encoder: Path,
    orig: Path,
    out_dir: Path,
    qp: int,
    threads: int,
    preset: str,
    profile: int,
    stage1_csv: Path,
    trace_base: Path,
    frames: int,
) -> List[str]:
    bitstream = out_dir / f"QP{qp}.vvc"
    rec = out_dir / f"QP{qp}_rec.yuv"
    additional = (
        f"{skip21_additional(profile)} "
        f"LardLfnst21StatFile={stage1_csv} "
        f"LardLfnstTraceFile={trace_base}"
    )
    return [
        str(encoder),
        "--preset",
        preset,
        "-i",
        str(orig),
        "-s",
        "3840x1920",
        "-r",
        "30",
        "--InputChromaFormat",
        "420",
        "-q",
        str(qp),
        "--qpa",
        "0",
        "-f",
        str(frames),
        "-ip",
        "1",
        "--mtprofile",
        "0",
        "--threads",
        str(threads),
        "--additional",
        additional,
        "-b",
        str(bitstream),
        "-o",
        str(rec),
    ]


def diagnostic_final_trace_csv(trace_base: Path) -> Path:
    return Path(str(trace_base) + ".final.csv")


def concatenate_csvs(csv_paths: Sequence[Path], out_csv: Path) -> None:
    if not csv_paths:
        raise ValueError("at least one diagnostic CSV is required")

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = None
    with out_csv.open("w", newline="", encoding="utf-8") as out_handle:
        writer = None
        for csv_path in csv_paths:
            with csv_path.open(newline="", encoding="utf-8-sig") as in_handle:
                reader = csv.DictReader(in_handle)
                if reader.fieldnames is None:
                    raise ValueError(f"diagnostic CSV has no header: {csv_path}")
                if fieldnames is None:
                    fieldnames = list(reader.fieldnames)
                    writer = csv.DictWriter(out_handle, fieldnames=fieldnames)
                    writer.writeheader()
                elif list(reader.fieldnames) != fieldnames:
                    raise ValueError(f"diagnostic CSV header mismatch: {csv_path}")

                assert writer is not None
                for row in reader:
                    writer.writerow(row)


def merge_diagnostic_profile_csvs(
    profile_stage1_csvs: Dict[str, Sequence[Path]],
    profile_final_trace_csvs: Dict[str, Sequence[Path]],
    out_root: Path,
) -> Dict[str, Dict[str, Any]]:
    diagnostic_stats: Dict[str, Dict[str, Any]] = {}
    for profile_name, csv_paths in sorted(profile_stage1_csvs.items()):
        profile_out = out_root / profile_name
        merged_stage1_csv = profile_out / "diagnostic_stage1.csv"
        merged_final_trace_csv = profile_out / "diagnostic_final_trace.csv"
        summary_json = profile_out / "diagnostic_summary.json"
        concatenate_csvs(csv_paths, merged_stage1_csv)
        concatenate_csvs(profile_final_trace_csvs[profile_name], merged_final_trace_csv)
        summary = summarize_stage1_stats(merged_stage1_csv, merged_final_trace_csv)
        summary_json.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        diagnostic_stats[profile_name] = summary
    return diagnostic_stats


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _prepare_fresh_outputs(paths: Sequence[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def _require_fresh_nonempty(path: Path, started_at: float) -> None:
    if not path.exists():
        raise RuntimeError(f"expected output was not created: {path}")
    stat = path.stat()
    if stat.st_size <= 0:
        raise RuntimeError(f"expected output is empty: {path}")
    if stat.st_mtime < started_at:
        raise RuntimeError(f"expected output is stale: {path}")


def _run_timing_job(
    name: str,
    profile: int,
    frames: int,
    repeats: int,
    args: argparse.Namespace,
    qps: Sequence[int],
) -> Dict[str, Any]:
    out_root = args.out_root / name / "timing"
    out_root.mkdir(parents=True, exist_ok=True)
    summary_json = out_root / "summary.json"
    cmd = timing_command(
        encoder=args.encoder,
        orig=args.orig,
        sphere_file=args.sphere_file,
        out_root=out_root,
        qps=qps,
        threads=args.threads,
        preset=args.preset,
        profile=profile,
        frames=frames,
        repeats=repeats,
    )
    _prepare_fresh_outputs([summary_json])
    started_at = time.time()
    subprocess.run(cmd, check=True)
    _require_fresh_nonempty(summary_json, started_at)
    return _read_json(summary_json)


def _run_diagnostics(
    args: argparse.Namespace, qps: Sequence[int]
) -> Dict[str, Dict[str, Any]]:
    profile_specs = (
        ("E5", 0),
        ("E10", 2),
        ("E12", 3),
        ("E15", 4),
        ("E12_noLat", 5),
        ("E15_noLat", 6),
    )
    profile_stage1_csvs: Dict[str, List[Path]] = {
        name: [] for name, _ in profile_specs
    }
    profile_final_trace_csvs: Dict[str, List[Path]] = {
        name: [] for name, _ in profile_specs
    }

    for profile_name, profile in profile_specs:
        for qp in qps:
            out_dir = args.out_root / profile_name / "diagnostic" / f"QP{qp}"
            out_dir.mkdir(parents=True, exist_ok=True)
            stage1_csv = out_dir / "stage1.csv"
            trace_base = out_dir / "trace.csv"
            final_trace_csv = diagnostic_final_trace_csv(trace_base)
            bitstream = out_dir / f"QP{qp}.vvc"
            rec = out_dir / f"QP{qp}_rec.yuv"
            cmd = diagnostic_command(
                encoder=args.encoder,
                orig=args.orig,
                out_dir=out_dir,
                qp=qp,
                threads=args.threads,
                preset=args.preset,
                profile=profile,
                stage1_csv=stage1_csv,
                trace_base=trace_base,
                frames=4,
            )
            _prepare_fresh_outputs([stage1_csv, final_trace_csv, bitstream, rec])
            started_at = time.time()
            subprocess.run(cmd, check=True)
            _require_fresh_nonempty(stage1_csv, started_at)
            _require_fresh_nonempty(final_trace_csv, started_at)
            profile_stage1_csvs[profile_name].append(stage1_csv)
            profile_final_trace_csvs[profile_name].append(final_trace_csv)

    return merge_diagnostic_profile_csvs(
        profile_stage1_csvs, profile_final_trace_csvs, args.out_root / "diagnostics"
    )


def _parse_qps(text: str) -> List[int]:
    return [int(value.strip()) for value in text.split(",") if value.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Skip21 stage-1 validation with separated timing and diagnostics."
    )
    parser.add_argument("--encoder", type=Path, required=True)
    parser.add_argument("--orig", type=Path, required=True)
    parser.add_argument("--sphere-file", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--qps", default="22,27,32,37")
    parser.add_argument("--threads", type=int, default=20)
    parser.add_argument("--preset", default="medium")
    parser.add_argument("--skip-diagnostics", action="store_true")
    parser.add_argument("--run-diagnostics", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    qps = _parse_qps(args.qps)
    args.out_root.mkdir(parents=True, exist_ok=True)

    timing_jobs: Dict[str, Any] = {}
    timing_jobs["E5_8f5"] = _run_timing_job("E5_8f5", 0, 8, 5, args, qps)
    timing_jobs["E10_4f10"] = _run_timing_job("E10_4f10", 2, 4, 10, args, qps)
    timing_jobs["E12_8f5"] = _run_timing_job("E12_8f5", 3, 8, 5, args, qps)
    timing_jobs["E15_8f5"] = _run_timing_job("E15_8f5", 4, 8, 5, args, qps)
    timing_jobs["E12_noLat_8f5"] = _run_timing_job("E12_noLat_8f5", 5, 8, 5, args, qps)
    timing_jobs["E15_noLat_8f5"] = _run_timing_job("E15_noLat_8f5", 6, 8, 5, args, qps)

    e10_overall = timing_jobs["E10_4f10"]["paired_timing"]["overall"]
    e10_fallback = e10_needs_8f_fallback(
        float(e10_overall["mean_TS_pct"]),
        float(e10_overall["median_TS_pct"]),
        int(e10_overall["positive_repeats"]),
    )
    if e10_fallback:
        timing_jobs["E10_8f5"] = _run_timing_job("E10_8f5", 2, 8, 5, args, qps)

    timing_result = {
        "jobs": timing_jobs,
        "e10_fallback_triggered": e10_fallback,
        "e10_selected_job": "E10_8f5" if e10_fallback else "E10_4f10",
    }
    diagnostic_stats = {} if args.skip_diagnostics else _run_diagnostics(args, qps)
    validation_summary = {
        "timing_result": timing_result,
        "diagnostic_stats": diagnostic_stats,
    }
    (args.out_root / "validation_summary.json").write_text(
        json.dumps(validation_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(validation_summary, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
