#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import stat

import paramiko


HOST = "ry2.9gpu.com"
PORT = 16021
USER = "root"
REMOTE_ROOT = "/root/vvenc_lard_exp/vvenc-1.12.0-lard-src"


FILES = [
    ("source/Lib/EncoderLib/IntraSearch.cpp", f"{REMOTE_ROOT}/source/Lib/EncoderLib/IntraSearch.cpp"),
    ("source/Lib/EncoderLib/IntraSearch.h", f"{REMOTE_ROOT}/source/Lib/EncoderLib/IntraSearch.h"),
    ("source/Lib/EncoderLib/LardLfnstCandGainTable.inc", f"{REMOTE_ROOT}/source/Lib/EncoderLib/LardLfnstCandGainTable.inc"),
    ("source/Lib/EncoderLib/LardLfnstFitTable.inc", f"{REMOTE_ROOT}/source/Lib/EncoderLib/LardLfnstFitTable.inc"),
    ("source/Lib/EncoderLib/LardLfnstModeSkipTable.inc", f"{REMOTE_ROOT}/source/Lib/EncoderLib/LardLfnstModeSkipTable.inc"),
    ("source/Lib/EncoderLib/LardLfnstSpeedTable.inc", f"{REMOTE_ROOT}/source/Lib/EncoderLib/LardLfnstSpeedTable.inc"),
    ("tools/lard_lfnst_analyze_trace.py", "/root/vvenc_lard_exp/tools/lard_lfnst_analyze_trace.py"),
    ("tools/lard_lfnst_conditional_effects.py", "/root/vvenc_lard_exp/tools/lard_lfnst_conditional_effects.py"),
]


def exec_checked(client: paramiko.SSHClient, command: str, timeout: int = 600) -> tuple[str, str]:
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if code != 0:
        raise RuntimeError(f"remote command failed ({code}): {command}\nSTDOUT:\n{out}\nSTDERR:\n{err}")
    return out, err


def mkdir_p(sftp: paramiko.SFTPClient, remote_dir: str) -> None:
    parts = Path(remote_dir).parts
    cur = ""
    for part in parts:
        if part == "/":
            cur = "/"
            continue
        cur = f"{cur.rstrip('/')}/{part}"
        try:
            sftp.stat(cur)
        except FileNotFoundError:
            sftp.mkdir(cur)


def main() -> None:
    password = os.environ["ERP_SERVER_PASSWORD"]
    local_root = Path.cwd()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=password, timeout=20)
    sftp = client.open_sftp()
    exec_checked(client, f"test -d {REMOTE_ROOT} && mkdir -p /root/vvenc_lard_exp/tools")
    for local_rel, remote in FILES:
        local = local_root / local_rel
        if not local.exists():
            raise FileNotFoundError(local)
        mkdir_p(sftp, str(Path(remote).parent))
        sftp.put(str(local), remote)
        if remote.endswith(".py"):
            mode = sftp.stat(remote).st_mode
            sftp.chmod(remote, mode | stat.S_IXUSR)
        print(f"uploaded {local_rel} -> {remote}")
    out, err = exec_checked(
        client,
        f"cd {REMOTE_ROOT} && python3 -m py_compile /root/vvenc_lard_exp/tools/lard_lfnst_analyze_trace.py /root/vvenc_lard_exp/tools/lard_lfnst_conditional_effects.py && grep -n \"absSum,corrProxy\" source/Lib/EncoderLib/IntraSearch.cpp | head",
        timeout=120,
    )
    print(out)
    if err:
        print(err)
    sftp.close()
    client.close()


if __name__ == "__main__":
    main()
