#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
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
)
from tools.lard_lfnst.run_skip21_stage2_validation import ANCHOR_ADDITIONAL, PROFILES


SEQ_RE = re.compile(
    r"^(?P<name>.+)_(?P<width>\d+)x(?P<height>\d+)_(?P<fps>\d+)fps_(?P<bitdepth>\d+)bit_420_erp\.yuv$"
)

CONFIGS: dict[str, dict[str, Any]] = {
    "RA": {"frames_from_gop": True, "refresh": "1"},
    "LD": {"frames_from_gop": True, "refresh": "0"},
    "AI": {"frames_from_gop": False, "refresh": "1"},
}


def parse_sequence(path: Path) -> dict[str, int | str | Path]:
    match = SEQ_RE.match(path.name)
    if not match:
        raise ValueError(f"cannot parse ERP sequence name: {path.name}")
    bitdepth = int(match.group("bitdepth"))
    width = int(match.group("width"))
    height = int(match.group("height"))
    bytes_per_sample = 2 if bitdepth > 8 else 1
    frame_bytes = width * height * 3 // 2 * bytes_per_sample
    return {
        "path": path,
        "name": match.group("name"),
        "width": width,
        "height": height,
        "fps": int(match.group("fps")),
        "bitdepth": bitdepth,
        "available_frames": path.stat().st_size // frame_bytes,
    }


def parse_csv_list(text: str) -> list[str]:
    return [value.strip() for value in text.split(",") if value.strip()]


def parse_qps(text: str) -> list[int]:
    return [int(value) for value in parse_csv_list(text)]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_cmd(cmd: list[str], log: Path) -> float:
    log.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    with log.open("w", encoding="utf-16") as handle:
        proc = subprocess.run(cmd, stdout=handle, stderr=subprocess.STDOUT, text=True)
    elapsed = time.perf_counter() - start
    if proc.returncode != 0:
        raise RuntimeError(f"encode failed ({proc.returncode}): {' '.join(cmd)}")
    return elapsed


def config_gop(config_name: str, args: argparse.Namespace) -> int:
    if config_name == "RA":
        return args.ra_gop
    if config_name == "LD":
        return args.ld_gop
    return 1


def config_frames(config_name: str, args: argparse.Namespace) -> int:
    config = CONFIGS[config_name]
    if config["frames_from_gop"]:
        return 2 * config_gop(config_name, args)
    return args.ai_frames


def config_args(config_name: str, args: argparse.Namespace) -> list[str]:
    gop = config_gop(config_name, args)
    if config_name == "LD":
        intra_period = "-1"
    else:
        intra_period = str(gop)
    result = ["--IntraPeriod", intra_period, "--GOPSize", str(gop), "--DecodingRefreshType", str(CONFIGS[config_name]["refresh"])]
    if config_name == "LD":
        result.extend(["--PicReordering", "0", "--POC0IDR", "1"])
    return result


def encode_case(
    encoder: Path,
    seq: dict[str, int | str | Path],
    out_dir: Path,
    config_name: str,
    qp: int,
    repeat: int,
    kind: str,
    additional: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    run_dir = out_dir / f"QP{qp}" / f"repeat{repeat}"
    run_dir.mkdir(parents=True, exist_ok=True)
    bitstream = run_dir / f"{kind}.vvc"
    rec = run_dir / f"{kind}_rec.yuv"
    log = run_dir / f"{kind}.log"
    for path in (bitstream, rec, log):
        path.unlink(missing_ok=True)

    frames = config_frames(config_name, args)
    cmd = [
        str(encoder),
        "--preset",
        args.preset,
        "-i",
        str(seq["path"]),
        "-s",
        f"{seq['width']}x{seq['height']}",
        "-r",
        str(seq["fps"]),
        "--InputChromaFormat",
        "420",
        "--InputBitDepth",
        str(seq["bitdepth"]),
        "-q",
        str(qp),
        "--qpa",
        "0",
        "-f",
        str(frames),
        "--mtprofile",
        "0",
        "--threads",
        str(args.threads),
        *config_args(config_name, args),
        "--additional",
        additional,
        "-b",
        str(bitstream),
        "-o",
        str(rec),
    ]
    seconds = run_cmd(cmd, log)
    bitrate, ord_y, ord_u, ord_v, ord_yuv = parse_log(log)
    row: dict[str, Any] = {
        "config": config_name,
        "repeat": repeat,
        "QP": qp,
        "kind": kind,
        "Seconds": seconds,
        "Kbps": bitrate,
        "Bytes": bitstream.stat().st_size,
        "SHA256": sha256(bitstream),
        "ORD_Y": ord_y,
        "ORD_U": ord_u,
        "ORD_V": ord_v,
        "ORD_YUV": ord_yuv,
    }
    try:
        if repeat == 1:
            row.update(
                compute_case_with_bitdepth(
                    Path(str(seq["path"])),
                    rec,
                    int(seq["width"]),
                    int(seq["height"]),
                    args.rec_bitdepth,
                    int(seq["bitdepth"]),
                    args.spsnr_table,
                    frames,
                )
            )
    finally:
        rec.unlink(missing_ok=True)
        if not args.keep_bitstreams:
            bitstream.unlink(missing_ok=True)
    return row


def paired_schedule(repeats: int) -> list[tuple[int, str]]:
    schedule: list[tuple[int, str]] = []
    for repeat in range(1, repeats + 1):
        order = ("anchor", "proposed") if repeat % 2 else ("proposed", "anchor")
        schedule.extend((repeat, kind) for kind in order)
    return schedule


def ts(anchor: float, proposed: float) -> float:
    return (anchor - proposed) / anchor * 100.0


def stats(values: list[float]) -> dict[str, float]:
    return {
        "mean_TS_pct": statistics.fmean(values),
        "median_TS_pct": statistics.median(values),
        "std_TS_pct": statistics.pstdev(values),
        "min_TS_pct": min(values),
        "max_TS_pct": max(values),
    }


def summarize_timing(rows: list[dict[str, Any]]) -> dict[str, Any]:
    indexed = {
        (int(row["repeat"]), int(row["QP"]), str(row["kind"])): float(row["Seconds"])
        for row in rows
    }
    repeats = sorted({key[0] for key in indexed})
    qps = sorted({key[1] for key in indexed})
    repeat_rows: list[dict[str, Any]] = []
    for repeat in repeats:
        anchor = sum(indexed[(repeat, qp, "anchor")] for qp in qps)
        proposed = sum(indexed[(repeat, qp, "proposed")] for qp in qps)
        repeat_rows.append({"repeat": repeat, "AnchorSeconds": anchor, "ProposedSeconds": proposed, "TS_pct": ts(anchor, proposed)})
    values = [float(row["TS_pct"]) for row in repeat_rows]
    by_qp: dict[str, Any] = {}
    for qp in qps:
        qp_values = [ts(indexed[(repeat, qp, "anchor")], indexed[(repeat, qp, "proposed")]) for repeat in repeats]
        by_qp[str(qp)] = {**stats(qp_values), "positive_pairs": sum(value > 0.0 for value in qp_values), "pairs": len(qp_values), "paired_TS_pct": qp_values}
    return {"repeats": repeat_rows, "overall": {**stats(values), "positive_repeats": sum(value > 0.0 for value in values), "repeats": len(values)}, "by_qp": by_qp}


def summarize_metrics(rows: list[dict[str, Any]], qps: list[int]) -> dict[str, float]:
    first = {(int(row["QP"]), str(row["kind"])): row for row in rows if int(row["repeat"]) == 1}
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


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def run_sequence_config_profile(
    seq: dict[str, int | str | Path],
    config_name: str,
    profile_name: str,
    args: argparse.Namespace,
    qps: list[int],
) -> dict[str, Any]:
    out_dir = args.out_root / config_name / profile_name / str(seq["name"])
    summary_path = out_dir / "summary.json"
    if args.resume and summary_path.exists():
        return json.loads(summary_path.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    args.spsnr_table = erp_spsnr_nn_indices(args.sphere_file, int(seq["width"]), int(seq["height"]))

    rows: list[dict[str, Any]] = []
    additions = {"anchor": ANCHOR_ADDITIONAL, "proposed": PROFILES[profile_name]}
    for repeat, kind in paired_schedule(args.repeats):
        for qp in qps:
            encoder = args.anchor_encoder if kind == "anchor" else args.encoder
            rows.append(encode_case(encoder, seq, out_dir, config_name, qp, repeat, kind, additions[kind], args))
    rows.sort(key=lambda row: (int(row["repeat"]), int(row["QP"]), str(row["kind"])))
    write_csv(out_dir / "encode_rows.csv", rows)

    summary = {
        "sequence": str(seq["name"]),
        "config": config_name,
        "profile": profile_name,
        "width": int(seq["width"]),
        "height": int(seq["height"]),
        "fps": int(seq["fps"]),
        "bitdepth": int(seq["bitdepth"]),
        "frames": config_frames(config_name, args),
        "gop": config_gop(config_name, args),
        "qps": qps,
        "repeats": args.repeats,
        "timing": summarize_timing(rows),
        "metrics": summarize_metrics(rows, qps),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--encoder", type=Path, required=True)
    parser.add_argument("--anchor-encoder", type=Path, default=None)
    parser.add_argument("--seq-root", type=Path, required=True)
    parser.add_argument("--sphere-file", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--qps", default="22,27,32,37")
    parser.add_argument("--configs", default="RA,LD,AI")
    parser.add_argument("--profiles", default="S12_A_E15_noLat_C1,S12_B_E12_noLat_C1")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--threads", type=int, default=20)
    parser.add_argument("--preset", default="medium")
    parser.add_argument("--ra-gop", type=int, default=16)
    parser.add_argument("--ld-gop", type=int, default=8)
    parser.add_argument("--ai-frames", type=int, default=8)
    parser.add_argument("--rec-bitdepth", type=int, default=10)
    parser.add_argument("--expect-count", type=int, default=14)
    parser.add_argument("--sequence-filter", default="")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--keep-bitstreams", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.anchor_encoder is None:
        args.anchor_encoder = args.encoder

    qps = parse_qps(args.qps)
    configs = parse_csv_list(args.configs)
    profiles = parse_csv_list(args.profiles)
    unknown_configs = [name for name in configs if name not in CONFIGS]
    unknown_profiles = [name for name in profiles if name not in PROFILES]
    if unknown_configs:
        raise ValueError(f"unknown config(s): {', '.join(unknown_configs)}")
    if unknown_profiles:
        raise ValueError(f"unknown profile(s): {', '.join(unknown_profiles)}")

    sequences = [parse_sequence(path) for path in sorted(args.seq_root.glob("*_erp.yuv"))]
    if args.sequence_filter:
        seq_re = re.compile(args.sequence_filter)
        sequences = [seq for seq in sequences if seq_re.search(str(seq["name"]))]
    if args.expect_count >= 0 and len(sequences) != args.expect_count:
        raise RuntimeError(f"expected {args.expect_count} ERP sequences under {args.seq_root}, found {len(sequences)}")
    for config_name in configs:
        frames = config_frames(config_name, args)
        too_short = [f"{seq['name']}({seq['available_frames']}f)" for seq in sequences if int(seq["available_frames"]) < frames]
        if too_short:
            raise RuntimeError(f"{config_name} requires {frames} frames, but sequence(s) are too short: {', '.join(too_short)}")

    args.out_root.mkdir(parents=True, exist_ok=True)
    run_config = {
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "anchor_encoder": str(args.anchor_encoder),
        "proposed_encoder": str(args.encoder),
        "qps": qps,
        "configs": configs,
        "profiles": profiles,
        "profile_additional": {name: PROFILES[name] for name in profiles},
        "frames": {name: config_frames(name, args) for name in configs},
        "gops": {name: config_gop(name, args) for name in configs},
        "threads": args.threads,
        "preset": args.preset,
        "repeats": args.repeats,
        "sequences": [str(seq["name"]) for seq in sequences],
    }
    (args.out_root / "run_config.json").write_text(json.dumps(run_config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(run_config, ensure_ascii=False), flush=True)
    if args.dry_run:
        print(json.dumps({"dry_run": True, "out_root": str(args.out_root)}, ensure_ascii=False), flush=True)
        return

    summaries: list[dict[str, Any]] = []
    total = len(sequences) * len(configs) * len(profiles)
    idx = 0
    for config_name in configs:
        for profile_name in profiles:
            for seq in sequences:
                idx += 1
                print(f"[{idx}/{total}] config={config_name} profile={profile_name} sequence={seq['name']}", flush=True)
                summary = run_sequence_config_profile(seq, config_name, profile_name, args, qps)
                summaries.append(summary)
                compact = {
                    "sequence": summary["sequence"],
                    "config": summary["config"],
                    "profile": summary["profile"],
                    "TS_pct": summary["timing"]["overall"]["median_TS_pct"],
                    "CPP_Y_BDBR_pct": summary["metrics"]["CPP_Y_BDBR_pct"],
                    "ByteDelta_pct": summary["metrics"]["ByteDelta_pct"],
                }
                print(json.dumps(compact, ensure_ascii=False), flush=True)

    flat_rows: list[dict[str, Any]] = []
    for summary in summaries:
        row = {
            "config": summary["config"],
            "profile": summary["profile"],
            "sequence": summary["sequence"],
            "frames": summary["frames"],
            "median_TS_pct": summary["timing"]["overall"]["median_TS_pct"],
            "positive_repeats": summary["timing"]["overall"]["positive_repeats"],
            "repeats": summary["timing"]["overall"]["repeats"],
            **summary["metrics"],
        }
        flat_rows.append(row)
    write_csv(args.out_root / "flat_summary.csv", flat_rows)

    aggregate: dict[str, Any] = {"finished": time.strftime("%Y-%m-%d %H:%M:%S"), "groups": {}}
    for config_name in configs:
        for profile_name in profiles:
            group_rows = [row for row in flat_rows if row["config"] == config_name and row["profile"] == profile_name]
            key = f"{config_name}/{profile_name}"
            aggregate["groups"][key] = {
                "sequence_count": len(group_rows),
                "avg_median_TS_pct": statistics.fmean(float(row["median_TS_pct"]) for row in group_rows),
                "max_CPP_Y_BDBR_pct": max(float(row["CPP_Y_BDBR_pct"]) for row in group_rows),
                "avg_CPP_Y_BDBR_pct": statistics.fmean(float(row["CPP_Y_BDBR_pct"]) for row in group_rows),
                "avg_ByteDelta_pct": statistics.fmean(float(row["ByteDelta_pct"]) for row in group_rows),
            }
    (args.out_root / "aggregate_summary.json").write_text(
        json.dumps({"configuration": run_config, "aggregate": aggregate, "sequences": summaries}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"aggregate": aggregate}, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
