#!/usr/bin/env python3
import argparse
import csv
import math
import subprocess
from pathlib import Path

import pandas as pd


SEQUENCES = {
    "DrivingInCity": {
        "file": r"I:\Sequences360\low\DrivingInCity_half_960x480_30Hz_8b_420.yuv",
        "width": 960,
        "height": 480,
        "framerate": 30,
        "class": "ERP",
    },
    "AerialCity": {
        "file": r"I:\Sequences360\low\AerialCity_half_960x480_30Hz_8b_420.yuv",
        "width": 960,
        "height": 480,
        "framerate": 30,
        "class": "ERP",
    },
    "BranCastle2": {
        "file": r"I:\Sequences360\low\BranCastle2_half_768x384_30Hz_8b_420.yuv",
        "width": 768,
        "height": 384,
        "framerate": 30,
        "class": "ERP",
    },
    "Johnny": {
        "file": r"I:\HEVC-test\Johnny_1280x720_60.yuv",
        "width": 1280,
        "height": 720,
        "framerate": 60,
        "class": "ordinary",
    },
    "FourPeople": {
        "file": r"I:\HEVC-test\FourPeople_1280x720_60.yuv",
        "width": 1280,
        "height": 720,
        "framerate": 60,
        "class": "ordinary",
    },
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def encoder_path(root: Path) -> Path:
    candidates = [
        root / "bin" / "vs16" / "msvc-19.29" / "x86_64" / "release" / "EncoderApp.exe",
        root / "bin" / "vs16" / "msvc-19.29" / "x86_64" / "debug" / "EncoderApp.exe",
        root / "bin" / "EncoderApp.exe",
        root / "EncoderAppStatic.exe",
        root / "EncoderApp.exe",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError("EncoderApp.exe not found. Build EncoderApp first.")


def qstep(qp: float) -> float:
    return math.pow(2.0, (float(qp) - 4.0) / 6.0)


def log_finished(path: Path) -> bool:
    try:
        return " finished @ " in path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def delete_rec_yuv(run_dir: Path):
    rec_path = run_dir / "rec.yuv"
    if rec_path.exists():
        rec_path.unlink()


def run_one(root: Path, enc: Path, seq_name: str, seq: dict, qp: int, frames: int,
            overwrite: bool, tag: str, resume: bool, keep_rec: bool) -> Path:
    exp_root = root / "experiments" / "rc360_frame_model"
    data_root = exp_root / "data" / tag if tag else exp_root / "data"
    run_root = exp_root / "runs" / tag if tag else exp_root / "runs"
    log_root = exp_root / "logs" / tag if tag else exp_root / "logs"
    ctu_dir = data_root / "ctu"
    run_dir = run_root / f"{seq_name}_qp{qp}"
    log_dir = log_root
    ctu_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    csv_path = ctu_dir / f"{seq_name}_qp{qp}.csv"
    stdout_path = log_dir / f"{seq_name}_qp{qp}_stdout.log"
    stderr_path = log_dir / f"{seq_name}_qp{qp}_stderr.log"

    if resume and csv_path.exists() and log_finished(stdout_path):
        print("SKIP", seq_name, "QP", qp, flush=True)
        if not keep_rec:
            delete_rec_yuv(run_dir)
        return csv_path

    if overwrite and csv_path.exists():
        csv_path.unlink()

    cmd = [
        str(enc),
        "-c", str(root / "cfg" / "encoder_lowdelay_P_vtm.cfg"),
        "-i", seq["file"],
        "-b", str(run_dir / "output.bin"),
        "-o", str(run_dir / "rec.yuv"),
        "-wdt", str(seq["width"]),
        "-hgt", str(seq["height"]),
        "-fr", str(seq["framerate"]),
        "-f", str(frames),
        "-q", str(qp),
        "--IntraPeriod=8",
        "--GOPSize=8",
        "--RateControl=0",
        "--RC360FbTc=0",
        "--RC360CtuExp=1",
        f"--RC360CtuExpFile={csv_path}",
        "--RC360CtuExpMaxStretch=9999",
        "--MaxDeltaQP=0",
        "--MaxCuDQPSubdiv=0",
        "--WaveFrontSynchro=0",
    ]

    print("RUN", seq_name, "QP", qp, "frames", frames, flush=True)
    with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout, \
            stderr_path.open("w", encoding="utf-8", errors="replace") as stderr:
        subprocess.run(cmd, cwd=str(root), check=True, stdout=stdout, stderr=stderr)

    if not keep_rec:
        delete_rec_yuv(run_dir)

    return csv_path


def combine_ctu_csv(files, out_file: Path):
    out_file.parent.mkdir(parents=True, exist_ok=True)
    header = None
    with out_file.open("w", newline="", encoding="utf-8") as dst:
        writer = None
        for file_name, seq_name, command_qp in files:
            if not file_name.exists():
                continue
            with file_name.open("r", newline="", encoding="utf-8") as src:
                reader = csv.reader(src)
                try:
                    current_header = next(reader)
                except StopIteration:
                    continue
                current_header = current_header + ["command_qp", "sequence_class"]
                if header is None:
                    header = current_header
                    writer = csv.writer(dst)
                    writer.writerow(header)
                for row in reader:
                    writer.writerow(row + [command_qp, SEQUENCES[seq_name]["class"]])


def aggregate_frames(ctu_files, out_file: Path):
    frames = []
    for csv_path, seq_name, command_qp in ctu_files:
        if not csv_path.exists():
            continue
        df = pd.read_csv(csv_path)
        if df.empty:
            continue
        df["ctu_area"] = df["w"] * df["h"]
        for poc, g in df.groupby("poc"):
            area = g["ctu_area"].sum()
            if area <= 0:
                continue
            weighted = lambda col: float((g[col] * g["ctu_area"]).sum() / area)
            frame_qp = weighted("qp")
            frames.append({
                "sequence": seq_name,
                "sequence_class": SEQUENCES[seq_name]["class"],
                "command_qp": command_qp,
                "poc": int(poc),
                "frame_qp": frame_qp,
                "qp": frame_qp,
                "qs": qstep(frame_qp),
                "command_qs": qstep(command_qp),
                "ctu_count": int(len(g)),
                "width": SEQUENCES[seq_name]["width"],
                "height": SEQUENCES[seq_name]["height"],
                "frame_area": int(area),
                "ieff_raw": float(g["ieff_raw"].mean()),
                "satd": float(g["satd"].sum()),
                "residual_energy": weighted("residual_energy"),
                "actual_bits": int(g["actual_bits"].sum()),
                "ordinary_mse": weighted("ordinary_mse"),
                "latitude_weighted_mse": weighted("latitude_weighted_mse"),
                "intra_ratio": weighted("intra_ratio"),
                "inter_ratio": weighted("inter_ratio"),
                "skip_ratio": weighted("skip_ratio"),
                "nonzero_coeff_ratio": weighted("nonzero_coeff_ratio"),
            })

    out_file.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(frames).to_csv(out_file, index=False)


def main():
    parser = argparse.ArgumentParser(description="Run RC360 frame-level model collection experiments.")
    parser.add_argument("--frames", type=int, default=32)
    parser.add_argument("--smoke", action="store_true", help="Run one sequence, QP32, two frames.")
    parser.add_argument("--overwrite", action="store_true", default=True)
    parser.add_argument("--qp-start", type=int, default=27)
    parser.add_argument("--qp-end", type=int, default=42)
    parser.add_argument("--qps", type=str, default="", help="Comma-separated QP list. Overrides qp-start/qp-end.")
    parser.add_argument("--skip-qps", type=str, default="", help="Comma-separated QPs to skip.")
    parser.add_argument("--tag", type=str, default="", help="Optional subdirectory tag under data/runs/logs.")
    parser.add_argument("--resume", action="store_true", help="Skip jobs that already have a finished stdout log and CSV.")
    parser.add_argument("--keep-rec", action="store_true", help="Keep reconstructed YUV files after CSV extraction.")
    args = parser.parse_args()

    root = repo_root()
    enc = encoder_path(root)
    if args.smoke:
        qps = [32]
    elif args.qps:
        qps = [int(x.strip()) for x in args.qps.split(",") if x.strip()]
    else:
        skip = {int(x.strip()) for x in args.skip_qps.split(",") if x.strip()}
        qps = [qp for qp in range(args.qp_start, args.qp_end + 1) if qp not in skip]
    frames = 2 if args.smoke else args.frames
    seq_items = [("DrivingInCity", SEQUENCES["DrivingInCity"])] if args.smoke else list(SEQUENCES.items())

    ctu_files = []
    for seq_name, seq in seq_items:
        for qp in qps:
            ctu_files.append((run_one(root, enc, seq_name, seq, qp, frames, args.overwrite, args.tag, args.resume,
                                      args.keep_rec), seq_name, qp))

    exp_root = root / "experiments" / "rc360_frame_model"
    data_root = exp_root / "data" / args.tag if args.tag else exp_root / "data"
    combine_ctu_csv(ctu_files, data_root / "all_ctu_samples.csv")
    aggregate_frames(ctu_files, data_root / "frame_samples.csv")
    print("Frame samples written.")


if __name__ == "__main__":
    main()
