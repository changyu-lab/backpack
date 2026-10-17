#!/usr/bin/env python3
from __future__ import annotations

import os
import paramiko


def main() -> None:
    password = os.environ["ERP_SERVER_PASSWORD"]
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("ry2.9gpu.com", port=16021, username="root", password=password, timeout=20)
    commands = [
        "hostname; pwd; df -h /root; ls -lah /root | head -40",
        "find /root -maxdepth 5 \\( -name vvencFFapp -o -name vvencFFapp.exe -o -name AerialCity_3840x1920_30fps_8bit_420_erp.yuv -o -name lard_lfnst_analyze_trace.py \\) 2>/dev/null | head -80",
    ]
    for command in commands:
        print(f"---CMD--- {command}")
        _, stdout, stderr = client.exec_command(command, timeout=120)
        print(stdout.read().decode("utf-8", errors="replace"))
        err = stderr.read().decode("utf-8", errors="replace")
        if err:
            print("---STDERR---")
            print(err)
    client.close()


if __name__ == "__main__":
    main()
