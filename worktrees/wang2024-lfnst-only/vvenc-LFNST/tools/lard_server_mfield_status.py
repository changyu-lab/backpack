#!/usr/bin/env python3
from __future__ import annotations

import os
import paramiko


COMMAND = r"""
set -e
OUT=/root/vvenc_lard_exp/aerialcity_mfield_fullrdo
echo "== processes =="
ps -eo pid,ppid,etime,cmd | grep -E 'run_mfield_trace_analysis|vvencFFapp|lard_lfnst_analyze_trace' | grep -v grep || true
echo "== progress files =="
for QP in 22 27 32 37; do
  DIR="$OUT/AerialCity_QP${QP}"
  printf "QP%s " "$QP"
  if [ -s "$DIR/trace.csv.final.csv" ]; then printf "final=yes "; else printf "final=no "; fi
  if [ -s "$DIR/blocks.csv" ]; then printf "blocks=yes "; else printf "blocks=no "; fi
  if [ -s "$DIR/trace.csv" ]; then printf "trace=%s " "$(du -h "$DIR/trace.csv" | awk '{print $1}')"; else printf "trace=0 "; fi
  if [ -s "$DIR/blocks.csv" ]; then printf "blocksSize=%s " "$(du -h "$DIR/blocks.csv" | awk '{print $1}')"; fi
  echo
done
echo "== disk =="
df -h /root
echo "== run.log =="
tail -40 "$OUT/run.log" 2>/dev/null || true
echo "== stdout =="
tail -20 /root/vvenc_lard_exp/logs/mfield_trace_analysis.stdout 2>/dev/null || true
echo "== stderr =="
tail -20 /root/vvenc_lard_exp/logs/mfield_trace_analysis.stderr 2>/dev/null || true
"""


def main() -> None:
    password = os.environ["ERP_SERVER_PASSWORD"]
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        "ry2.9gpu.com",
        port=16021,
        username="root",
        password=password,
        timeout=60,
        banner_timeout=90,
        auth_timeout=60,
    )
    _, stdout, stderr = client.exec_command(COMMAND, timeout=120)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print(out, end="" if out.endswith("\n") else "\n")
    if err:
        print("---STDERR---")
        print(err, end="" if err.endswith("\n") else "\n")
    code = stdout.channel.recv_exit_status()
    client.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
