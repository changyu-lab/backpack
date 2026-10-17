#!/usr/bin/env python3
from __future__ import annotations

import os
import fnmatch
from pathlib import Path

import paramiko


HOST = "ry2.9gpu.com"
PORT = 16021
USER = "root"
REMOTE_DIR = os.environ.get("REMOTE_DIR", "/root/vvenc_lard_exp/runs/lfnst2nd_aerialcity3840_param_scan")
LOCAL_DIR = Path(os.environ.get("LOCAL_DIR", "lahtp_runs/lfnst2nd_aerialcity3840_param_scan_server"))
KEEP_NAMES = {
    "scan_summary.csv",
    "metric_curve.csv",
    "metrics.json",
    "lfnst2nd_counts.csv",
    "run_summary.csv",
    "eval.stdout",
    "raw_runs.csv",
    "paired_repeats.csv",
    "paired_by_qp.csv",
    "hash_stability.csv",
    "summary.json",
    "validation_summary.json",
    "diagnostic_summary.json",
    "diagnostic_stage1.csv",
    "diagnostic_final_trace.csv",
}
KEEP_PATTERNS = (
    "skip18_qp*_stats.csv",
    "stage1.csv",
    "trace.csv",
    "trace.csv.final.csv",
    "trace.final.csv",
    "*diagnostic*.csv",
    "*final_trace*.csv",
    "*stage1*.csv",
)


def fetch_tree(sftp: paramiko.SFTPClient, remote_dir: str, local_dir: Path) -> None:
    local_dir.mkdir(parents=True, exist_ok=True)
    for item in sftp.listdir_attr(remote_dir):
        name = item.filename
        remote = f"{remote_dir}/{name}"
        local = local_dir / name
        mode = item.st_mode or 0
        if (mode & 0o170000) == 0o040000:
            fetch_tree(sftp, remote, local)
        elif name in KEEP_NAMES or any(fnmatch.fnmatch(name, pattern) for pattern in KEEP_PATTERNS):
            sftp.get(remote, str(local))
            print(f"fetched {remote} -> {local} ({item.st_size} bytes)")


def main() -> None:
    password = os.environ.get("ERP_SERVER_PASSWORD")
    key_path = Path(os.environ.get("ERP_SERVER_KEY", str(Path.home() / ".ssh" / "codex_ry2_ipm")))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = dict(hostname=HOST, port=PORT, username=USER, timeout=60, banner_timeout=90)
    if password:
        kwargs["password"] = password
    elif key_path.exists():
        kwargs["key_filename"] = str(key_path)
    else:
        raise RuntimeError("set ERP_SERVER_PASSWORD or ERP_SERVER_KEY")
    client.connect(**kwargs)
    sftp = client.open_sftp()
    fetch_tree(sftp, REMOTE_DIR, LOCAL_DIR)
    sftp.close()
    client.close()


if __name__ == "__main__":
    main()
