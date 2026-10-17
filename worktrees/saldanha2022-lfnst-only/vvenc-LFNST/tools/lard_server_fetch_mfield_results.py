#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

import paramiko


REMOTE_DIR = "/root/vvenc_lard_exp/conditional_mfield_lfnst_effects"
LOCAL_DIR = Path("lahtp_runs/conditional_mfield_lfnst_effects_server")
SKIP_NAMES = {"lfnst_conditional_features.pkl", "matched_pairs_low_high_latitude.csv"}


def main() -> None:
    password = os.environ["ERP_SERVER_PASSWORD"]
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("ry2.9gpu.com", port=16021, username="root", password=password, timeout=60, banner_timeout=90)
    sftp = client.open_sftp()
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    for item in sftp.listdir_attr(REMOTE_DIR):
        name = item.filename
        if name in SKIP_NAMES:
            continue
        remote = f"{REMOTE_DIR}/{name}"
        local = LOCAL_DIR / name
        if item.st_mode and (item.st_mode & 0o170000) == 0o040000:
            continue
        sftp.get(remote, str(local))
        print(f"fetched {name} ({item.st_size} bytes)")
    sftp.close()
    client.close()


if __name__ == "__main__":
    main()
