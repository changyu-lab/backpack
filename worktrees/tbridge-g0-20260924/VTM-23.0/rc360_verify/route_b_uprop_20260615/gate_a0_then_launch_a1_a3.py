#!/usr/bin/env python3
import csv
import math
import subprocess
import time
from pathlib import Path

import numpy as np


A0_ROOT = Path("/root/rc360_route_b_20260615/fullres_ablation_fixed/B0_server_same_binary")
REFERENCE_CSV = Path("/root/rc360_route_b_20260615/windows_ablation_point_summary.csv")
LAUNCH_SCRIPT = Path("/root/VTM-23.0-route-b-a3/run_server_a1_a3.sh")
STATUS = Path("/root/rc360_route_b_20260615/a0_gate_status.log")
QPS = (22, 27, 32, 37)


def log(message):
    with STATUS.open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {message}\n")


def wait_for_a0():
    while True:
        states = []
        for qp in QPS:
            exit_file = A0_ROOT / f"QP{qp}" / "exit_code.txt"
            states.append(exit_file.read_text().strip() if exit_file.exists() else "running")
        log("A0 states=" + ",".join(f"QP{qp}:{state}" for qp, state in zip(QPS, states)))
        if all(state != "running" for state in states):
            if any(state != "0" for state in states):
                raise RuntimeError(f"A0 failed: {states}")
            return
        time.sleep(120)


def parse_summary(log_path):
    summary = None
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.lstrip().startswith("16") and " a " in line:
            values = [float(v) for v in line.split(" a ", 1)[1].split()]
            summary = {
                "rate": values[0] * 1000.0,
                "Y": values[1],
                "Y_WS": values[5],
                "Y_S": values[8],
                "Y_CPP": values[14],
            }
    if summary is None:
        raise RuntimeError(f"missing aggregate summary in {log_path}")
    return summary


def load_reference():
    result = {}
    with REFERENCE_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["mode"] == "B0":
                label = row["label"]
                qp = int(label[2:] if label.startswith("QP") else label)
                result[qp] = {
                    "rate": float(row["actual_bps"]),
                    "Y": float(row["Y_PSNR"]),
                    "Y_WS": float(row["Y_WS"]),
                    "Y_S": float(row["Y_S"]),
                    "Y_CPP": float(row["Y_CPP"]),
                }
    return result


def bd_rate(reference, test, metric):
    ref_rate = np.array([reference[qp]["rate"] for qp in QPS], dtype=float)
    test_rate = np.array([test[qp]["rate"] for qp in QPS], dtype=float)
    ref_quality = np.array([reference[qp][metric] for qp in QPS], dtype=float)
    test_quality = np.array([test[qp][metric] for qp in QPS], dtype=float)
    low = max(ref_quality.min(), test_quality.min())
    high = min(ref_quality.max(), test_quality.max())
    if high <= low:
        raise RuntimeError(f"no overlapping quality interval for {metric}")
    ref_poly = np.polyfit(ref_quality, np.log(ref_rate), 3)
    test_poly = np.polyfit(test_quality, np.log(test_rate), 3)
    ref_int = np.polyint(ref_poly)
    test_int = np.polyint(test_poly)
    average_log_delta = (
        np.polyval(test_int, high) - np.polyval(test_int, low)
        - np.polyval(ref_int, high) + np.polyval(ref_int, low)
    ) / (high - low)
    return 100.0 * (math.exp(average_log_delta) - 1.0)


def main():
    wait_for_a0()
    reference = load_reference()
    test = {qp: parse_summary(A0_ROOT / f"QP{qp}" / "encode.log") for qp in QPS}
    bd = {metric: bd_rate(reference, test, metric) for metric in ("Y", "Y_WS", "Y_S", "Y_CPP")}
    max_rate_delta = max(
        abs(100.0 * (test[qp]["rate"] / reference[qp]["rate"] - 1.0))
        for qp in QPS
    )
    log("A0 BD-rate vs Windows B0 " + " ".join(f"{key}={value:+.6f}%" for key, value in bd.items()))
    log(f"A0 max point bitrate delta={max_rate_delta:.6f}%")

    sphere_ok = all(abs(bd[metric]) <= 0.1 for metric in ("Y_WS", "Y_S", "Y_CPP"))
    if not sphere_ok or max_rate_delta > 0.2:
        log("GATE FAILED; A1/A3 not launched")
        raise SystemExit(2)

    log("GATE PASSED; launching A1/A3")
    with Path("/root/rc360_route_b_20260615/a1_a3.nohup.log").open("wb") as output:
        subprocess.Popen(
            [str(LAUNCH_SCRIPT)],
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


if __name__ == "__main__":
    main()
