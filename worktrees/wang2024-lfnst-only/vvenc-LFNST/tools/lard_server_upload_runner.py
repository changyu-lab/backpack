#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import stat

import paramiko


def main() -> None:
    password = os.environ["ERP_SERVER_PASSWORD"]
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("ry2.9gpu.com", port=16021, username="root", password=password, timeout=20)
    sftp = client.open_sftp()
    local = Path.cwd() / "tools" / "server_run_mfield_trace_analysis.sh"
    remote = "/root/vvenc_lard_exp/run_mfield_trace_analysis.sh"
    sftp.put(str(local), remote)
    mode = sftp.stat(remote).st_mode
    sftp.chmod(remote, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    sftp.close()
    _, stdout, stderr = client.exec_command(f"bash -n {remote} && ls -lh {remote}", timeout=60)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    print(out, end="")
    if err:
        print(err, end="")
    client.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
