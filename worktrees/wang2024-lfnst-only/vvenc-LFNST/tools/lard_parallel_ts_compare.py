#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from lard_360_metrics import bdrate, compute_case_with_bitdepth, erp_spsnr_nn_indices, parse_log


def run_cmd(cmd: list[str], log: Path) -> float:
    log.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    with log.open("w", encoding="utf-16") as fh:
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, text=True)
    elapsed = time.perf_counter() - start
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")
    return elapsed


def encode_case(exe: Path, orig: Path, out_dir: Path, name: str, qp: int, args: argparse.Namespace, additional: str) -> dict[str, float | int | str]:
    qdir = out_dir / name / f"QP{qp}"
    qdir.mkdir(parents=True, exist_ok=True)
    bitstream = qdir / f"{name}.vvc"
    rec = qdir / f"{name}_rec.yuv"
    log = qdir / f"{name}.log"
    for p in (bitstream, rec, log):
        p.unlink(missing_ok=True)

    cmd = [
        str(exe),
        "--preset", args.preset,
        "-i", str(orig),
        "-s", f"{args.width}x{args.height}",
        "-r", str(args.fps),
        "--InputChromaFormat", "420",
        "-q", str(qp),
        "--qpa", "0",
        "-f", str(args.frames),
        "-ip", "1",
        "--mtprofile", "0",
        "--threads", str(args.threads),
        "--additional", additional,
        "-b", str(bitstream),
        "-o", str(rec),
    ]
    elapsed = run_cmd(cmd, log)
    bitrate, _, _, _, _ = parse_log(log)
    return {
        "case": name,
        "QP": qp,
        "Seconds": elapsed,
        "Kbps": bitrate,
        "Bytes": bitstream.stat().st_size,
        "rec": str(rec),
        "bitstream": str(bitstream),
        "log": str(log),
    }


def bd_summary(anchor_rows: list[dict[str, float | int | str]], test_rows: list[dict[str, float | int | str]]) -> dict[str, float]:
    a_by_qp = {int(r["QP"]): r for r in anchor_rows}
    t_by_qp = {int(r["QP"]): r for r in test_rows}
    qps = sorted(a_by_qp)
    out: dict[str, float] = {}
    rates_a = [float(a_by_qp[qp]["Kbps"]) for qp in qps]
    rates_t = [float(t_by_qp[qp]["Kbps"]) for qp in qps]
    for metric in ("WS", "S", "CPP"):
        key = f"{metric}_YUV"
        out[f"{key}_BDBR_pct"] = bdrate(
            rates_a,
            [float(a_by_qp[qp][key]) for qp in qps],
            rates_t,
            [float(t_by_qp[qp][key]) for qp in qps],
        )
    anchor_time = sum(float(a_by_qp[qp]["Seconds"]) for qp in qps)
    test_time = sum(float(t_by_qp[qp]["Seconds"]) for qp in qps)
    out["AnchorTime_sec"] = anchor_time
    out["TestTime_sec"] = test_time
    out["TS_pct"] = (anchor_time - test_time) / anchor_time * 100.0
    out["ByteDelta_pct"] = (
        sum(int(t_by_qp[qp]["Bytes"]) for qp in qps) - sum(int(a_by_qp[qp]["Bytes"]) for qp in qps)
    ) / sum(int(a_by_qp[qp]["Bytes"]) for qp in qps) * 100.0
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-root", type=Path, default=Path("/root/vvenc_lard_exp/vvenc-1.12.0-lard-src"))
    ap.add_argument("--orig", type=Path, default=Path("/root/sequences360_32f/AerialCity_3840x1920_30fps_8bit_420_erp.yuv"))
    ap.add_argument("--sphere-file", type=Path, default=Path("/root/vvenc_lard_exp/sphere_655362.txt"))
    ap.add_argument("--out-root", type=Path, default=Path("/root/vvenc_lard_exp/runs/parallel_ts_compare4f"))
    ap.add_argument("--qps", default="22,27,32,37")
    ap.add_argument("--width", type=int, default=3840)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--frames", type=int, default=4)
    ap.add_argument("--threads", type=int, default=20)
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--orig-bitdepth", type=int, default=8)
    ap.add_argument("--rec-bitdepth", type=int, default=10)
    args = ap.parse_args()

    args.out_root.mkdir(parents=True, exist_ok=True)
    base_exe = args.src_root / "bin/release-static/vvencFFapp"
    if not base_exe.exists():
        base_exe = args.src_root / "bin/release-shared/vvencFFapp"
    if not base_exe.exists():
        raise FileNotFoundError(base_exe)

    exe_dir = args.out_root / "exe"
    exe_dir.mkdir(parents=True, exist_ok=True)
    exes = {}
    for name in ("anchor", "paper", "proposed"):
        dst = exe_dir / f"vvenc_{name}"
        shutil.copy2(base_exe, dst)
        dst.chmod(0o755)
        exes[name] = dst

    additions = {
        "anchor": "LFNST=1 LardLfnstSkip=0",
        "paper": (
            "LFNST=1 LardLfnstSkip=12 "
            "LardLfnstPaperGradTh1=100 LardLfnstPaperTh2Scale=12.83 "
            "LardLfnstPaperTh2Offset1=17.375 LardLfnstPaperTh2Offset2=57.375"
        ),
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

    qps = [int(x) for x in args.qps.split(",") if x]
    spsnr_table = erp_spsnr_nn_indices(args.sphere_file, args.width, args.height)

    rows: list[dict[str, float | int | str]] = []

    def run_group(name: str) -> list[dict[str, float | int | str]]:
        group_rows = []
        for qp in qps:
            r = encode_case(exes[name], args.orig, args.out_root, name, qp, args, additions[name])
            metrics = compute_case_with_bitdepth(
                args.orig, Path(str(r["rec"])), args.width, args.height,
                args.rec_bitdepth, args.orig_bitdepth, spsnr_table, args.frames
            )
            r.update(metrics)
            Path(str(r["rec"])).unlink(missing_ok=True)
            group_rows.append(r)
        return group_rows

    started = time.strftime("%Y-%m-%d %H:%M:%S")
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {pool.submit(run_group, name): name for name in ("anchor", "paper", "proposed")}
        for fut in as_completed(futs):
            rows.extend(fut.result())
            print(f"finished {futs[fut]}", flush=True)

    rows.sort(key=lambda r: (str(r["case"]), int(r["QP"])))
    with (args.out_root / "parallel_metric_curve.csv").open("w", newline="", encoding="utf-8") as fh:
        fields = [k for k in rows[0].keys() if k not in ("rec", "bitstream", "log")]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r[k] for k in fields})

    by_case = {name: [r for r in rows if r["case"] == name] for name in ("anchor", "paper", "proposed")}
    summary = {
        "started": started,
        "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
        "paper": bd_summary(by_case["anchor"], by_case["paper"]),
        "proposed": bd_summary(by_case["anchor"], by_case["proposed"]),
    }
    (args.out_root / "parallel_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
