#!/usr/bin/env python3
"""Run a calibrated Skip21 Stage-3 QARD profile on one sequence.

Use the `stage3_qard_real.additional.txt` emitted by calibrate_skip21_stage3_qard.py.
This runner deliberately disables Stage-3 CSV logging by default so wall-clock timing is not polluted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import time
from pathlib import Path


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


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_total_time(log: Path) -> float | None:
    pat = re.compile(r"Total Time:\s*([0-9.]+)\s*sec")
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        m = pat.search(line)
        if m:
            return float(m.group(1))
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--encoder", type=Path, required=True)
    ap.add_argument("--orig", type=Path, required=True)
    ap.add_argument("--additional-file", type=Path, required=True)
    ap.add_argument("--size", required=True, help="WxH")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--bitdepth", type=int, default=10)
    ap.add_argument("--qps", default="22,27,32,37")
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--config", choices=("AI", "RA", "LD"), default="AI")
    ap.add_argument("--gop", type=int, default=8)
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    additional_base = args.additional_file.read_text(encoding="utf-8").strip()
    if not additional_base:
        raise RuntimeError(f"{args.additional_file}: empty additional string")
    if "LardLfnst21Stage3RdeMode=2" not in additional_base:
        raise RuntimeError("additional file is not a calibrated real-pruning profile (Stage3RdeMode=2 missing)")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    input_format = "yuv420_10" if args.bitdepth == 10 else "yuv420"
    cli_config, extra_config = config_args(args.config, args.gop)
    runs: list[dict[str, object]] = []

    for qp in parse_qps(args.qps):
        for rep in range(args.repeats):
            stem = f"qard_real_QP{qp}_r{rep}"
            bitstream = args.out_dir / f"{stem}.vvc"
            log = args.out_dir / f"{stem}.log"
            additional = f"{additional_base} {extra_config}"
            cmd = [
                str(args.encoder), "--preset", args.preset, "-i", str(args.orig), "-s", args.size,
                "-r", str(args.fps), "-c", input_format, "-q", str(qp), "--qpa", "0",
                "-f", str(args.frames), "--mtprofile", "0", "--threads", str(args.threads),
                *cli_config, "--additional", additional, "-o", str(bitstream),
            ]
            print(" ".join(shlex.quote(x) for x in cmd))
            if args.dry_run:
                continue
            t0 = time.perf_counter()
            with log.open("w", encoding="utf-8") as fh:
                proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT)
            wall = time.perf_counter() - t0
            if proc.returncode:
                raise RuntimeError(f"QP{qp} repeat {rep} failed; see {log}")
            runs.append({
                "qp": qp,
                "repeat": rep,
                "wall_seconds": wall,
                "encoder_total_seconds": parse_total_time(log),
                "sha256": sha256(bitstream),
                "bitstream": str(bitstream),
                "log": str(log),
            })

    if not args.dry_run:
        manifest = args.out_dir / "qard_real_manifest.json"
        manifest.write_text(json.dumps({"additional_file": str(args.additional_file.resolve()), "runs": runs}, indent=2) + "\n", encoding="utf-8")
        print(f"manifest={manifest}")


if __name__ == "__main__":
    main()
