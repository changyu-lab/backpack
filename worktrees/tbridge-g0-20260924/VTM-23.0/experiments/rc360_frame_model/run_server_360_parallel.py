#!/usr/bin/env python3
import argparse
import csv
import math
import os
import re
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def sanitize_name(stem: str) -> str:
    stem = re.sub(r"[_-]\d+x\d+.*$", "", stem)
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem)
    return stem.strip("_") or "sequence"


def parse_sequence(path: Path, default_framerate: int):
    m = re.search(r"(\d+)x(\d+)", path.name)
    if not m:
        raise ValueError(f"Cannot parse resolution from YUV filename: {path.name}")
    width = int(m.group(1))
    height = int(m.group(2))

    framerate = default_framerate
    fr_match = re.search(r"[_-](\d+)(?:Hz|hz|fps|FPS)", path.name)
    if fr_match:
        framerate = int(fr_match.group(1))

    bitdepth = 8
    bit_match = re.search(r"[_-](8|10|12)bit", path.name, re.IGNORECASE)
    if bit_match:
        bitdepth = int(bit_match.group(1))

    return {
        "name": sanitize_name(path.stem),
        "file": str(path),
        "width": width,
        "height": height,
        "framerate": framerate,
        "bitdepth": bitdepth,
        "class": "ERP",
    }


def discover_sequences(input_dir: Path, default_framerate: int, limit: int):
    yuvs = sorted(input_dir.glob("*.yuv"))
    if limit > 0:
        yuvs = yuvs[:limit]
    sequences = [parse_sequence(path, default_framerate) for path in yuvs]
    if not sequences:
        raise FileNotFoundError(f"No .yuv files found under {input_dir}")

    names = {}
    for seq in sequences:
        base = seq["name"]
        idx = names.get(base, 0)
        names[base] = idx + 1
        if idx > 0:
            seq["name"] = f"{base}_{idx + 1}"
    return sequences


def encoder_path(root: Path, override: str):
    if override:
        path = Path(override)
        if path.exists():
            return path
        raise FileNotFoundError(f"Encoder not found: {path}")

    candidates = [
        root / "bin" / "EncoderAppStatic",
        root / "bin" / "EncoderApp",
        root / "EncoderAppStatic",
        root / "EncoderApp",
        root / "bin" / "vs16" / "msvc-19.29" / "x86_64" / "release" / "EncoderApp.exe",
    ]
    candidates.extend(sorted((root / "bin").glob("umake/**/EncoderAppStatic")))
    candidates.extend(sorted((root / "bin").glob("umake/**/EncoderApp")))
    candidates.extend(sorted((root / "bin").glob("gcc*/**/EncoderAppStatic")))
    candidates.extend(sorted((root / "bin").glob("gcc*/**/EncoderApp")))
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError("EncoderApp/EncoderAppStatic not found. Pass --encoder explicitly.")


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


def run_one(root: str, enc: str, tag: str, seq: dict, qp: int, frames: int, resume: bool, overwrite: bool,
            keep_rec: bool):
    root = Path(root)
    enc = Path(enc)
    exp_root = root / "experiments" / "rc360_frame_model"
    data_root = exp_root / "data" / tag
    run_root = exp_root / "runs" / tag
    log_root = exp_root / "logs" / tag
    ctu_dir = data_root / "ctu"
    run_dir = run_root / f"{seq['name']}_qp{qp}"
    ctu_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    log_root.mkdir(parents=True, exist_ok=True)

    csv_path = ctu_dir / f"{seq['name']}_qp{qp}.csv"
    stdout_path = log_root / f"{seq['name']}_qp{qp}_stdout.log"
    stderr_path = log_root / f"{seq['name']}_qp{qp}_stderr.log"

    if resume and csv_path.exists() and log_finished(stdout_path):
        if not keep_rec:
            delete_rec_yuv(run_dir)
        return {"sequence": seq["name"], "qp": qp, "status": "skipped", "csv": str(csv_path)}

    if overwrite and csv_path.exists():
        csv_path.unlink()

    rec_path = str(run_dir / "rec.yuv")

    cmd = [
        str(enc),
        "-c", str(root / "cfg" / "encoder_lowdelay_P_vtm.cfg"),
        "-i", seq["file"],
        "-b", str(run_dir / "output.bin"),
        "-o", rec_path,
        "-wdt", str(seq["width"]),
        "-hgt", str(seq["height"]),
        "-fr", str(seq["framerate"]),
        "-f", str(frames),
        "-q", str(qp),
        f"--InputBitDepth={seq['bitdepth']}",
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

    with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout, \
            stderr_path.open("w", encoding="utf-8", errors="replace") as stderr:
        ret = subprocess.run(cmd, cwd=str(root), stdout=stdout, stderr=stderr)

    if not keep_rec:
        delete_rec_yuv(run_dir)

    status = "done" if ret.returncode == 0 else f"failed:{ret.returncode}"
    return {"sequence": seq["name"], "qp": qp, "status": status, "csv": str(csv_path)}


def run_group(group_id: int, sequences, qps, root: str, enc: str, tag: str, frames: int, resume: bool,
              overwrite: bool, keep_rec: bool):
    results = []
    for seq in sequences:
        for qp in qps:
            print(f"[group {group_id}] RUN {seq['name']} QP {qp}", flush=True)
            result = run_one(root, enc, tag, seq, qp, frames, resume, overwrite, keep_rec)
            print(f"[group {group_id}] {result['status']} {seq['name']} QP {qp}", flush=True)
            results.append(result)
    return results


def combine_ctu_csv(completed, sequences_by_name, out_file: Path):
    out_file.parent.mkdir(parents=True, exist_ok=True)
    header = None
    with out_file.open("w", newline="", encoding="utf-8") as dst:
        writer = None
        for csv_path, seq_name, command_qp in completed:
            csv_path = Path(csv_path)
            if not csv_path.exists() or csv_path.stat().st_size == 0:
                continue
            with csv_path.open("r", newline="", encoding="utf-8") as src:
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
                    writer.writerow(row + [command_qp, sequences_by_name[seq_name]["class"]])


def aggregate_frames(completed, sequences_by_name, out_file: Path):
    frames = []
    for csv_path, seq_name, command_qp in completed:
        csv_path = Path(csv_path)
        if not csv_path.exists() or csv_path.stat().st_size == 0:
            continue
        seq = sequences_by_name[seq_name]
        by_poc = {}
        with csv_path.open("r", newline="", encoding="utf-8") as src:
            reader = csv.DictReader(src)
            for row in reader:
                poc = int(float(row["poc"]))
                acc = by_poc.setdefault(poc, {
                    "area": 0.0,
                    "ctu_count": 0,
                    "ieff_sum": 0.0,
                    "satd_sum": 0.0,
                    "actual_bits_sum": 0.0,
                    "weighted": {
                        "qp": 0.0,
                        "residual_energy": 0.0,
                        "ordinary_mse": 0.0,
                        "latitude_weighted_mse": 0.0,
                        "intra_ratio": 0.0,
                        "inter_ratio": 0.0,
                        "skip_ratio": 0.0,
                        "nonzero_coeff_ratio": 0.0,
                    },
                })
                area = float(row["w"]) * float(row["h"])
                acc["area"] += area
                acc["ctu_count"] += 1
                acc["ieff_sum"] += float(row["ieff_raw"])
                acc["satd_sum"] += float(row["satd"])
                acc["actual_bits_sum"] += float(row["actual_bits"])
                for col in acc["weighted"]:
                    acc["weighted"][col] += float(row[col]) * area

        for poc, acc in sorted(by_poc.items()):
            area = acc["area"]
            if area <= 0.0 or acc["ctu_count"] <= 0:
                continue
            weighted = lambda col: acc["weighted"][col] / area
            frame_qp = weighted("qp")
            frames.append({
                "sequence": seq_name,
                "sequence_class": seq["class"],
                "command_qp": command_qp,
                "poc": poc,
                "frame_qp": frame_qp,
                "qp": frame_qp,
                "qs": qstep(frame_qp),
                "command_qs": qstep(command_qp),
                "ctu_count": acc["ctu_count"],
                "width": seq["width"],
                "height": seq["height"],
                "frame_area": int(area),
                "ieff_raw": acc["ieff_sum"] / acc["ctu_count"],
                "satd": acc["satd_sum"],
                "residual_energy": weighted("residual_energy"),
                "actual_bits": int(acc["actual_bits_sum"]),
                "ordinary_mse": weighted("ordinary_mse"),
                "latitude_weighted_mse": weighted("latitude_weighted_mse"),
                "intra_ratio": weighted("intra_ratio"),
                "inter_ratio": weighted("inter_ratio"),
                "skip_ratio": weighted("skip_ratio"),
                "nonzero_coeff_ratio": weighted("nonzero_coeff_ratio"),
            })

    out_file.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "sequence", "sequence_class", "command_qp", "poc", "frame_qp", "qp", "qs", "command_qs",
        "ctu_count", "width", "height", "frame_area", "ieff_raw", "satd", "residual_energy",
        "actual_bits", "ordinary_mse", "latitude_weighted_mse", "intra_ratio", "inter_ratio",
        "skip_ratio", "nonzero_coeff_ratio",
    ]
    with out_file.open("w", newline="", encoding="utf-8") as dst:
        writer = csv.DictWriter(dst, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(frames)


def write_manifest(sequences, out_file: Path):
    out_file.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["name", "file", "width", "height", "framerate", "bitdepth", "class"]
    with out_file.open("w", newline="", encoding="utf-8") as dst:
        writer = csv.DictWriter(dst, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sequences)


def write_dicts(rows, out_file: Path):
    out_file.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with out_file.open("w", newline="", encoding="utf-8") as dst:
        writer = csv.DictWriter(dst, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Parallel server runner for 360 YUV frame-level data collection.")
    parser.add_argument("--input-dir", default="/data/360sequence_20f")
    parser.add_argument("--tag", default="server_360_14seq_3f_qp17_50")
    parser.add_argument("--frames", type=int, default=3)
    parser.add_argument("--qp-start", type=int, default=17)
    parser.add_argument("--qp-end", type=int, default=50)
    parser.add_argument("--skip-qps", default="", help="Comma-separated QPs to skip. Default: none.")
    parser.add_argument("--jobs", type=int, default=4, help="Number of sequence groups to encode in parallel.")
    parser.add_argument("--limit", type=int, default=14)
    parser.add_argument("--default-framerate", type=int, default=30)
    parser.add_argument("--encoder", default="")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--keep-rec", action="store_true", help="Keep reconstructed YUV files after CSV extraction.")
    args = parser.parse_args()

    root = repo_root()
    enc = encoder_path(root, args.encoder)
    input_dir = Path(args.input_dir)
    sequences = discover_sequences(input_dir, args.default_framerate, args.limit)
    sequences_by_name = {seq["name"]: seq for seq in sequences}
    skip = {int(x.strip()) for x in args.skip_qps.split(",") if x.strip()}
    qps = [qp for qp in range(args.qp_start, args.qp_end + 1) if qp not in skip]

    exp_root = root / "experiments" / "rc360_frame_model"
    data_root = exp_root / "data" / args.tag
    write_manifest(sequences, data_root / "sequence_manifest.csv")

    jobs = max(1, min(args.jobs, len(sequences)))
    groups = [[] for _ in range(jobs)]
    for idx, seq in enumerate(sequences):
        groups[idx % jobs].append(seq)

    print(f"encoder={enc}")
    print(f"input_dir={input_dir}")
    print(f"sequences={len(sequences)} qps={len(qps)} frames={args.frames} jobs={jobs}")
    print("sequence_groups=" + "; ".join(",".join(seq["name"] for seq in group) for group in groups))

    all_results = []
    with ProcessPoolExecutor(max_workers=jobs) as executor:
        futures = [
            executor.submit(run_group, group_id, group, qps, str(root), str(enc), args.tag, args.frames,
                            args.resume, args.overwrite, args.keep_rec)
            for group_id, group in enumerate(groups)
            if group
        ]
        for future in as_completed(futures):
            all_results.extend(future.result())

    write_dicts(all_results, data_root / "job_status.csv")
    completed = [
        (row["csv"], row["sequence"], int(row["qp"]))
        for row in all_results
        if row["status"] in ("done", "skipped")
    ]
    combine_ctu_csv(completed, sequences_by_name, data_root / "all_ctu_samples.csv")
    aggregate_frames(completed, sequences_by_name, data_root / "frame_samples.csv")

    failed = [row for row in all_results if row["status"] not in ("done", "skipped")]
    if failed:
        write_dicts(failed, data_root / "failed_jobs.csv")
        print(f"failed_jobs={len(failed)} see {data_root / 'failed_jobs.csv'}")
    print(f"completed_or_skipped={len(completed)}")
    print(f"frame_samples={data_root / 'frame_samples.csv'}")


if __name__ == "__main__":
    main()
