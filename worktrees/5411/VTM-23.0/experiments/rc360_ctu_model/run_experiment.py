#!/usr/bin/env python3
import argparse
import csv
import subprocess
from pathlib import Path


SEQUENCES = {
    "DrivingInCity": {
        "file": r"I:\Sequences360\low\DrivingInCity_half_960x480_30Hz_8b_420.yuv",
        "width": 960,
        "height": 480,
    },
    "AerialCity": {
        "file": r"I:\Sequences360\low\AerialCity_half_960x480_30Hz_8b_420.yuv",
        "width": 960,
        "height": 480,
    },
    "BranCastle2": {
        "file": r"I:\Sequences360\low\BranCastle2_half_768x384_30Hz_8b_420.yuv",
        "width": 768,
        "height": 384,
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


def run_one(root: Path, enc: Path, seq_name: str, seq: dict, qp: int, frames: int,
            max_stretch: float, overwrite: bool) -> Path:
    exp_root = root / "experiments" / "rc360_ctu_model"
    data_dir = exp_root / "data"
    run_dir = exp_root / "runs" / f"{seq_name}_qp{qp}"
    log_dir = exp_root / "logs"
    data_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    csv_path = data_dir / f"{seq_name}_qp{qp}.csv"
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
        "-fr", "30",
        "-f", str(frames),
        "-q", str(qp),
        "--IntraPeriod=8",
        "--GOPSize=8",
        "--RateControl=0",
        "--RC360FbTc=0",
        "--RC360CtuExp=1",
        f"--RC360CtuExpFile={csv_path}",
        f"--RC360CtuExpMaxStretch={max_stretch}",
        "--MaxDeltaQP=0",
        "--MaxCuDQPSubdiv=0",
        "--WaveFrontSynchro=0",
    ]

    stdout_path = log_dir / f"{seq_name}_qp{qp}_stdout.log"
    stderr_path = log_dir / f"{seq_name}_qp{qp}_stderr.log"
    print("RUN", seq_name, "QP", qp)
    with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout, \
            stderr_path.open("w", encoding="utf-8", errors="replace") as stderr:
        subprocess.run(cmd, cwd=str(root), check=True, stdout=stdout, stderr=stderr)

    return csv_path


def combine_csv(data_files, out_file: Path):
    out_file.parent.mkdir(parents=True, exist_ok=True)
    header = None
    with out_file.open("w", newline="", encoding="utf-8") as dst:
        writer = None
        for file_name in data_files:
            if not file_name.exists():
                continue
            with file_name.open("r", newline="", encoding="utf-8") as src:
                reader = csv.reader(src)
                try:
                    current_header = next(reader)
                except StopIteration:
                    continue
                if header is None:
                    header = current_header
                    writer = csv.writer(dst)
                    writer.writerow(header)
                for row in reader:
                    writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description="Run RC360 CTU model collection experiments.")
    parser.add_argument("--frames", type=int, default=8)
    parser.add_argument("--smoke", action="store_true", help="Run two frames at QP32 only.")
    parser.add_argument("--max-stretch", type=float, default=1.2)
    parser.add_argument("--overwrite", action="store_true", default=True)
    args = parser.parse_args()

    root = repo_root()
    enc = encoder_path(root)
    qps = [32] if args.smoke else [27, 32, 37, 42]
    frames = 2 if args.smoke else args.frames

    csv_files = []
    for seq_name, seq in SEQUENCES.items():
      for qp in qps:
        csv_files.append(run_one(root, enc, seq_name, seq, qp, frames, args.max_stretch, args.overwrite))

    combine_csv(csv_files, root / "experiments" / "rc360_ctu_model" / "data" / "all_ctu_samples.csv")
    print("Combined CSV written.")


if __name__ == "__main__":
    main()
