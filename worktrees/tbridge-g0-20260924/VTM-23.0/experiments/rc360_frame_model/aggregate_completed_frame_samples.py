#!/usr/bin/env python3
import argparse
import re
import subprocess
from pathlib import Path

from run_frame_experiment import aggregate_frames, combine_ctu_csv


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_log_name(name: str):
    m = re.match(r"(.+)_qp(\d+)_stdout\.log$", name)
    if not m:
        return None
    return m.group(1), int(m.group(2))


def log_finished(path: Path) -> bool:
    try:
        return " finished @ " in path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description="Aggregate and optionally fit completed frame experiment jobs.")
    parser.add_argument("--tag", required=True, help="Source tag under data/logs.")
    parser.add_argument("--out-tag", required=True, help="Snapshot tag under data.")
    parser.add_argument("--fit", action="store_true")
    args = parser.parse_args()

    root = repo_root()
    exp_root = root / "experiments" / "rc360_frame_model"
    log_dir = exp_root / "logs" / args.tag
    ctu_dir = exp_root / "data" / args.tag / "ctu"
    out_data = exp_root / "data" / args.out_tag
    out_results = exp_root / f"results_{args.out_tag}"

    completed = []
    for log_path in sorted(log_dir.glob("*_stdout.log")):
        parsed = parse_log_name(log_path.name)
        if parsed is None or not log_finished(log_path):
            continue
        seq_name, qp = parsed
        csv_path = ctu_dir / f"{seq_name}_qp{qp}.csv"
        if csv_path.exists() and csv_path.stat().st_size > 0:
            completed.append((csv_path, seq_name, qp))

    out_data.mkdir(parents=True, exist_ok=True)
    combine_ctu_csv(completed, out_data / "all_ctu_samples.csv")
    aggregate_frames(completed, out_data / "frame_samples.csv")
    print(f"completed_jobs={len(completed)}")
    print(f"frame_samples={out_data / 'frame_samples.csv'}")

    if args.fit:
        subprocess.run(
            [
                "python",
                str(exp_root / "fit_frame_models.py"),
                "--input",
                str(out_data / "frame_samples.csv"),
                "--results-dir",
                str(out_results),
            ],
            cwd=str(root),
            check=True,
        )
        print(f"fit_results={out_results}")


if __name__ == "__main__":
    main()
