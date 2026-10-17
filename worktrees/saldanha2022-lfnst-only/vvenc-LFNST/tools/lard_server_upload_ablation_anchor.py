#!/usr/bin/env python3
from __future__ import annotations

import os
import stat
from pathlib import Path

import paramiko


def put(sftp: paramiko.SFTPClient, local: Path, remote: str, executable: bool = False) -> None:
    sftp.put(str(local), remote)
    if executable:
        mode = sftp.stat(remote).st_mode
        sftp.chmod(remote, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main() -> None:
    password = os.environ["ERP_SERVER_PASSWORD"]
    root = Path.cwd()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("ry2.9gpu.com", port=16021, username="root", password=password, timeout=60, banner_timeout=180, auth_timeout=180)
    sftp = client.open_sftp()
    try:
        try:
            sftp.mkdir("/root/vvenc_lard_exp/tools")
        except OSError:
            pass
        put(sftp, root / "tools" / "server_run_ablation_anchor.sh", "/root/vvenc_lard_exp/server_run_ablation_anchor.sh", True)
        put(sftp, root / "tools" / "lard_lfnst_ablation_experiments.py", "/root/vvenc_lard_exp/tools/lard_lfnst_ablation_experiments.py", False)
        put(sftp, root / "tools" / "lard_lfnst_analyze_trace.py", "/root/vvenc_lard_exp/tools/lard_lfnst_analyze_trace.py", False)
    finally:
        sftp.close()
    _, stdout, stderr = client.exec_command(
        "bash -n /root/vvenc_lard_exp/server_run_ablation_anchor.sh && python3 -m py_compile /root/vvenc_lard_exp/tools/lard_lfnst_ablation_experiments.py && ls -lh /root/vvenc_lard_exp/server_run_ablation_anchor.sh",
        timeout=120,
    )
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out:
        print(out, end="")
    if err:
        print(err, end="")
    client.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
