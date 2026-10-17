#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from lard_360_metrics import bdrate, compute_case_with_bitdepth, erp_spsnr_nn_indices, parse_log


SEQ_RE = re.compile(
    r"^(?P<name>.+)_(?P<width>\d+)x(?P<height>\d+)_(?P<fps>\d+)fps_(?P<bitdepth>\d+)bit_420_erp\.yuv$"
)


def parse_sequence(path: Path) -> dict[str, int | str | Path]:
    m = SEQ_RE.match(path.name)
    if not m:
        raise ValueError(f"cannot parse ERP sequence name: {path.name}")
    return {
        "path": path,
        "name": m.group("name"),
        "width": int(m.group("width")),
        "height": int(m.group("height")),
        "fps": int(m.group("fps")),
        "bitdepth": int(m.group("bitdepth")),
    }


def run_cmd(cmd: list[str], log: Path) -> float:
    log.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    with log.open("w", encoding="utf-16") as fh:
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, text=True)
    elapsed = time.perf_counter() - start
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")
    return elapsed


def encode_case(
    exe: Path,
    seq: dict[str, int | str | Path],
    out_dir: Path,
    case: str,
    qp: int,
    frames: int,
    threads: int,
    preset: str,
    additional: str,
) -> dict[str, float | int | str]:
    qdir = out_dir / case / f"QP{qp}"
    qdir.mkdir(parents=True, exist_ok=True)
    bitstream = qdir / f"{case}.vvc"
    rec = qdir / f"{case}_rec.yuv"
    log = qdir / f"{case}.log"
    for p in (bitstream, rec, log):
        p.unlink(missing_ok=True)

    cmd = [
        str(exe),
        "--preset",
        preset,
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
    elapsed = run_cmd(cmd, log)
    bitrate, _, _, _, _ = parse_log(log)
    return {
        "case": case,
        "QP": qp,
        "Seconds": elapsed,
        "Kbps": bitrate,
        "Bytes": bitstream.stat().st_size,
        "rec": str(rec),
        "bitstream": str(bitstream),
        "log": str(log),
    }


def summarize(anchor_rows: list[dict[str, float | int | str]], proposed_rows: list[dict[str, float | int | str]]) -> dict[str, float]:
    a_by_qp = {int(r["QP"]): r for r in anchor_rows}
    p_by_qp = {int(r["QP"]): r for r in proposed_rows}
    qps = sorted(a_by_qp)
    rates_a = [float(a_by_qp[qp]["Kbps"]) for qp in qps]
    rates_p = [float(p_by_qp[qp]["Kbps"]) for qp in qps]
    out: dict[str, float] = {}
    for metric in ("WS", "S", "CPP"):
        key = f"{metric}_YUV"
        out[f"{key}_BDBR_pct"] = (
            bdrate(
                rates_a,
                [float(a_by_qp[qp][key]) for qp in qps],
                rates_p,
                [float(p_by_qp[qp][key]) for qp in qps],
            )
            if len(qps) >= 4
            else float("nan")
        )
    anchor_time = sum(float(a_by_qp[qp]["Seconds"]) for qp in qps)
    proposed_time = sum(float(p_by_qp[qp]["Seconds"]) for qp in qps)
    out["AnchorTime_sec"] = anchor_time
    out["ProposedTime_sec"] = proposed_time
    out["TS_pct"] = (anchor_time - proposed_time) / anchor_time * 100.0
    out["ByteDelta_pct"] = (
        sum(int(p_by_qp[qp]["Bytes"]) for qp in qps) - sum(int(a_by_qp[qp]["Bytes"]) for qp in qps)
    ) / sum(int(a_by_qp[qp]["Bytes"]) for qp in qps) * 100.0
    return out


def write_curve(rows: list[dict[str, float | int | str]], path: Path) -> None:
    fields = [k for k in rows[0].keys() if k not in ("rec", "bitstream", "log")]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in fields})


def run_sequence(
    seq: dict[str, int | str | Path],
    args: argparse.Namespace,
    exes: dict[str, Path],
    additions: dict[str, str],
) -> dict[str, float | int | str]:
    qps = [int(x) for x in args.qps.split(",") if x]
    seq_dir = args.out_root / str(seq["name"])
    done = seq_dir / "summary.json"
    if args.resume and done.exists():
        cached = json.loads(done.read_text(encoding="utf-8"))
        return cached

    table = erp_spsnr_nn_indices(args.sphere_file, int(seq["width"]), int(seq["height"]))

    def run_group(case: str) -> list[dict[str, float | int | str]]:
        rows = []
        for qp in qps:
            row = encode_case(
                exes[case],
                seq,
                seq_dir,
                case,
                qp,
                args.frames,
                args.threads,
                args.preset,
                additions[case],
            )
            metrics = compute_case_with_bitdepth(
                Path(str(seq["path"])),
                Path(str(row["rec"])),
                int(seq["width"]),
                int(seq["height"]),
                args.rec_bitdepth,
                int(seq["bitdepth"]),
                table,
                args.frames,
            )
            row.update(metrics)
            Path(str(row["rec"])).unlink(missing_ok=True)
            rows.append(row)
        return rows

    if args.parallel_cases:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futs = {pool.submit(run_group, case): case for case in ("anchor", "proposed")}
            by_case = {futs[fut]: fut.result() for fut in as_completed(futs)}
    else:
        by_case = {"anchor": run_group("anchor"), "proposed": run_group("proposed")}

    rows = by_case["anchor"] + by_case["proposed"]
    rows.sort(key=lambda r: (str(r["case"]), int(r["QP"])))
    write_curve(rows, seq_dir / "metric_curve.csv")

    summary = summarize(by_case["anchor"], by_case["proposed"])
    summary_row: dict[str, float | int | str] = {
        "sequence": str(seq["name"]),
        "width": int(seq["width"]),
        "height": int(seq["height"]),
        "fps": int(seq["fps"]),
        "bitdepth": int(seq["bitdepth"]),
        **summary,
    }
    done.write_text(json.dumps(summary_row, indent=2), encoding="utf-8")
    return summary_row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-root", type=Path, default=Path("/root/vvenc_lard_exp/vvenc-1.12.0-lard-src"))
    ap.add_argument("--seq-root", type=Path, default=Path("/root/sequences360_32f"))
    ap.add_argument("--sphere-file", type=Path, default=Path("/root/VTM-23.0-rc360-server/cfg-360Lib/360Lib/sphere_655362.txt"))
    ap.add_argument("--out-root", type=Path, default=Path("/root/vvenc_lard_exp/runs/erp14_latest_4f"))
    ap.add_argument("--qps", default="22,27,32,37")
    ap.add_argument("--frames", type=int, default=4)
    ap.add_argument("--threads", type=int, default=20)
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--rec-bitdepth", type=int, default=10)
    ap.add_argument("--parallel-cases", action="store_true", help="run anchor/proposed concurrently per sequence")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--sequence-filter", default="", help="optional regex over parsed sequence names")
    ap.add_argument("--expect-count", type=int, default=14)
    args = ap.parse_args()

    args.out_root.mkdir(parents=True, exist_ok=True)
    base_exe = args.src_root / "bin/release-static/vvencFFapp"
    if not base_exe.exists():
        base_exe = args.src_root / "bin/release-shared/vvencFFapp"
    if not base_exe.exists():
        raise FileNotFoundError(base_exe)

    exe_dir = args.out_root / "exe"
    exe_dir.mkdir(parents=True, exist_ok=True)
    exes: dict[str, Path] = {}
    for case in ("anchor", "proposed"):
        dst = exe_dir / f"vvenc_{case}"
        shutil.copy2(base_exe, dst)
        dst.chmod(0o755)
        exes[case] = dst

    additions = {
        "anchor": "LFNST=1 LardLfnstSkip=0",
        "proposed": (
            "LFNST=1 LardLfnstSkip=13 LardLfnst13Fusion=1 "
            "LardLfnstTheoryTable=1 LardLfnst2ndCorrTable=0 "
            "LardLfnst2ndZeta=0.1 LardLfnst2ndDelta=0.25 LardLfnst2ndRidx=1.0 "
            "LardLfnst2ndCorrAlpha=0.0 LardLfnst2ndCorrDecay=2.0 "
            "LardLfnst2ndSafeMargin=0.0 LardLfnst2ndObsGate=-1000000000.0 "
            "LardLfnst2ndStage1Relax=1.0 "
            "LardLfnst2ndMaxCuQp=63 LardLfnst2ndMinArea=0 LardLfnst2ndMaxAspect=4 "
            "LardLfnst2ndShapeMask=31 "
            "LardLfnst2ndEffColsGate=1 LardLfnst2ndEffColsMin=2 "
            "LardLfnst2ndEffColsMinQp22=6 LardLfnst2ndEffColsMinQp27=6 "
            "LardLfnst2ndEffColsMinQp32=3 LardLfnst2ndEffColsMinQp37=0 "
            "LardLfnst11MaxCuQp=34 LardLfnst11MinArea=64 "
            "LardLfnstPaperGradTh1=75 LardLfnstPaperTh2Scale=12.83 "
            "LardLfnstPaperTh2Offset1=17.375 LardLfnstPaperTh2Offset2=57.375"
        ),
    }

    sequences = [parse_sequence(p) for p in sorted(args.seq_root.glob("*_erp.yuv"))]
    if args.sequence_filter:
        seq_re = re.compile(args.sequence_filter)
        sequences = [s for s in sequences if seq_re.search(str(s["name"]))]
    if args.expect_count >= 0 and len(sequences) != args.expect_count:
        raise RuntimeError(f"expected {args.expect_count} ERP sequences under {args.seq_root}, found {len(sequences)}")

    print(json.dumps({"started": time.strftime("%Y-%m-%d %H:%M:%S"), "sequences": [s["name"] for s in sequences]}, ensure_ascii=False), flush=True)
    summaries: list[dict[str, float | int | str]] = []
    for idx, seq in enumerate(sequences, start=1):
        print(f"[{idx}/14] {seq['name']} {seq['width']}x{seq['height']} {seq['bitdepth']}bit", flush=True)
        row = run_sequence(seq, args, exes, additions)
        summaries.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    keys = ["WS_YUV_BDBR_pct", "S_YUV_BDBR_pct", "CPP_YUV_BDBR_pct", "TS_pct", "ByteDelta_pct"]
    aggregate = {
        "started": summaries[0].get("started", ""),
        "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
        "frames": args.frames,
        "threads": args.threads,
        "preset": args.preset,
        "sequence_count": len(summaries),
        **{f"avg_{k}": sum(float(r[k]) for r in summaries) / len(summaries) for k in keys},
    }

    with (args.out_root / "sequence_summary.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(summaries[0].keys()))
        writer.writeheader()
        writer.writerows(summaries)
    (args.out_root / "aggregate_summary.json").write_text(
        json.dumps({"aggregate": aggregate, "sequences": summaries}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"aggregate": aggregate}, indent=2), flush=True)


if __name__ == "__main__":
    main()
