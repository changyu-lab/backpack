import gzip
import os
import re
import shutil
import sys
import time

import paramiko

HOST = "ry2.9gpu.com"
PORT = 16021
USER = "root"
PASSWORD = "7qS9cMwb"

LOCAL_SEQ_DIR = r"I:\Sequences360"
LOCAL_WORK_DIR = r"I:\vvenc-LFNST\server_migration\clips"
REMOTE_SEQ_DIR = "/root/sequences360_32f"
FRAMES = 32

INFO_RE = re.compile(r"_(\d+)x(\d+)_.*?_(\d+)bit_420_", re.IGNORECASE)

def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(os.path.join(os.path.dirname(__file__), "upload_clips.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")

def parse_info(name):
    m = INFO_RE.search(name)
    if not m:
        raise ValueError(f"Cannot parse resolution/bitdepth from {name}")
    w, h, bit = map(int, m.groups())
    bytes_per_sample = 2 if bit > 8 else 1
    frame_size = w * h * 3 // 2 * bytes_per_sample
    return w, h, bit, frame_size

def remote_size(client, path):
    cmd = f"stat -c '%s' {shell_quote(path)} 2>/dev/null || true"
    _, stdout, _ = client.exec_command(cmd)
    s = stdout.read().decode().strip()
    return int(s) if s else -1

def shell_quote(s):
    return "'" + s.replace("'", "'\"'\"'") + "'"

def compress_first_bytes(src, gz_path, nbytes):
    os.makedirs(os.path.dirname(gz_path), exist_ok=True)
    tmp = gz_path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    remaining = nbytes
    with open(src, "rb") as fin, gzip.open(tmp, "wb", compresslevel=1) as fout:
        while remaining > 0:
            chunk = fin.read(min(16 * 1024 * 1024, remaining))
            if not chunk:
                break
            fout.write(chunk)
            remaining -= len(chunk)
    os.replace(tmp, gz_path)

def main():
    os.makedirs(LOCAL_WORK_DIR, exist_ok=True)
    files = []
    for name in os.listdir(LOCAL_SEQ_DIR):
        if not name.lower().endswith(".yuv"):
            continue
        w, h, bit, frame_size = parse_info(name)
        src = os.path.join(LOCAL_SEQ_DIR, name)
        clip_bytes = frame_size * FRAMES
        files.append((0 if (w, h) == (3840, 1920) else 1, name, src, clip_bytes, w, h, bit))
    files.sort()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=30)
    client.exec_command(f"mkdir -p {shell_quote(REMOTE_SEQ_DIR)}")[1].channel.recv_exit_status()
    sftp = client.open_sftp()

    try:
        for _, name, src, clip_bytes, w, h, bit in files:
            remote_yuv = f"{REMOTE_SEQ_DIR}/{name}"
            existing = remote_size(client, remote_yuv)
            if existing == clip_bytes:
                log(f"SKIP remote exists {name} bytes={existing}")
                continue

            gz_name = name + ".gz"
            local_gz = os.path.join(LOCAL_WORK_DIR, gz_name)
            log(f"COMPRESS {name} {w}x{h} {bit}bit first_bytes={clip_bytes}")
            compress_first_bytes(src, local_gz, clip_bytes)
            gz_size = os.path.getsize(local_gz)
            log(f"UPLOAD {gz_name} compressed_bytes={gz_size}")
            remote_gz = f"{REMOTE_SEQ_DIR}/{gz_name}"
            remote_tmp = remote_gz + ".upload"
            try:
                sftp.remove(remote_tmp)
            except IOError:
                pass
            sftp.put(local_gz, remote_tmp)
            sftp.rename(remote_tmp, remote_gz)
            log(f"DECOMPRESS remote {gz_name}")
            cmd = f"cd {shell_quote(REMOTE_SEQ_DIR)} && rm -f {shell_quote(name)} && gzip -df {shell_quote(gz_name)} && stat -c '%s' {shell_quote(name)}"
            stdin, stdout, stderr = client.exec_command(cmd, timeout=3600)
            out = stdout.read().decode().strip()
            err = stderr.read().decode().strip()
            code = stdout.channel.recv_exit_status()
            if code != 0:
                raise RuntimeError(f"remote decompress failed for {name}: {err}")
            final_size = int(out.splitlines()[-1])
            if final_size != clip_bytes:
                raise RuntimeError(f"remote size mismatch for {name}: got {final_size}, expected {clip_bytes}")
            os.remove(local_gz)
            log(f"DONE {name} remote_bytes={final_size}; local gz removed")
    finally:
        sftp.close()
        client.close()

if __name__ == "__main__":
    main()
