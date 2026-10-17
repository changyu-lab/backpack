#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import time

import paramiko


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    password = os.environ.get("ERP_SERVER_PASSWORD")
    key_path = Path(os.environ.get("ERP_SERVER_KEY", str(Path.home() / ".ssh" / "codex_ry2_ipm")))
    last_exc: Exception | None = None
    for attempt in range(1, 11):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            kwargs = dict(hostname="ry2.9gpu.com", port=16021, username="root", timeout=60, banner_timeout=180, auth_timeout=180)
            if password:
                kwargs["password"] = password
            elif key_path.exists():
                kwargs["key_filename"] = str(key_path)
            else:
                raise RuntimeError("set ERP_SERVER_PASSWORD or ERP_SERVER_KEY")
            client.connect(**kwargs)
            break
        except Exception as exc:
            last_exc = exc
            try:
                client.close()
            except Exception:
                pass
            if attempt == 10:
                raise
            time.sleep(30)
    _, stdout, stderr = client.exec_command(args.command, timeout=args.timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out:
        print(out, end="" if out.endswith("\n") else "\n")
    if err:
        print(err, end="" if err.endswith("\n") else "\n")
    client.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
