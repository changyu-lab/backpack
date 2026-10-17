#!/usr/bin/env python3
"""Collect per-QP full-RDO shadow CSVs for the new Skip21 Stage-3 covariance-QARD model."""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import time
from pathlib import Path

from tools.lard_lfnst.calibrate_skip21_stage3_qard import qard_additional


def parse_qps(text: str) -> list[int]:
    return [int(v.strip()) for v in text.split(",") if v.strip()]


def config_args(name: str, gop: int) -> tuple[list[str], str]:
    name = name.upper()
    if name == "AI":
        return ["--intraperiod", "1", "--refreshtype", "idr"], "GOPSize=1"
    if name == "RA":
        return ["--intraperiod", str(gop), "--refreshtype", "cra"], f"GOPSize={gop}"
    if name == "LD":
        return ["--intraperiod", "-1", "--refreshtype", "idr"], f"GOPSize={gop} PicReordering=0 POC0IDR=1"
    raise ValueError(f"unknown config {name}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--encoder", type=Path, required=True)
    ap.add_argument("--orig", type=Path, required=True)
    ap.add_argument("--size", required=True, help="WxH")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--bitdepth", type=int, default=10)
    ap.add_argument("--qps", default="22,27,32,37")
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--config", choices=("AI", "RA", "LD"), default="AI")
    ap.add_argument("--gop", type=int, default=8)
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--threads", type=int, default=1, help="use 1 for deterministic calibration logs")
    ap.add_argument("--profile", type=int, choices=(0, 1, 2), default=1)
    ap.add_argument("--model", type=int, choices=(2, 3), default=3)
    ap.add_argument("--kappa-h", type=float, default=32.0)
    ap.add_argument("--kappa-v", type=float, default=32.0)
    ap.add_argument("--rho-base-h", type=float, default=0.6)
    ap.add_argument("--rho-base-v", type=float, default=0.6)
    ap.add_argument("--idx-bits", type=float, default=1.0)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    runs = []
    for qp in parse_qps(args.qps):
        stat = (args.out_dir / f"qard_shadow_QP{qp}.csv").resolve()
        log = args.out_dir / f"qard_shadow_QP{qp}.log"
        bitstream = args.out_dir / f"qard_shadow_QP{qp}.vvc"
        input_format = "yuv420_10" if args.bitdepth == 10 else "yuv420"
        cli_config, additional_config = config_args(args.config, args.gop)
        additional = qard_additional(
            1, args.profile, 1e9, kappa_h=args.kappa_h, kappa_v=args.kappa_v,
            rho_h=args.rho_base_h, rho_v=args.rho_base_v, idx_bits=args.idx_bits, model=args.model, stat_file=str(stat),
        ) + " " + additional_config
        cmd = [
            str(args.encoder), "--preset", args.preset, "-i", str(args.orig), "-s", args.size,
            "-r", str(args.fps), "-c", input_format,
            "-q", str(qp), "--qpa", "0", "-f", str(args.frames), "--mtprofile", "0", "--threads", str(args.threads),
            *cli_config, "--additional", additional, "-o", str(bitstream),
        ]
        print(" ".join(shlex.quote(x) for x in cmd))
        if args.dry_run:
            continue
        stat.unlink(missing_ok=True)
        t0 = time.perf_counter()
        with log.open("w", encoding="utf-8") as fh:
            proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT)
        elapsed = time.perf_counter() - t0
        if proc.returncode:
            raise RuntimeError(f"QP{qp} failed; see {log}")
        runs.append({"qp": qp, "seconds": elapsed, "csv": str(stat), "log": str(log), "bitstream": str(bitstream)})
    if not args.dry_run:
        manifest = args.out_dir / "qard_shadow_manifest.json"
        manifest.write_text(json.dumps({"runs": runs}, indent=2) + "\n", encoding="utf-8")
        print(f"manifest={manifest}")


if __name__ == "__main__":
    main()
