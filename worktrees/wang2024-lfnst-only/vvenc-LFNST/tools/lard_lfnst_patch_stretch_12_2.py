#!/usr/bin/env python3
"""Generate SJTU patch-level controlled-stretch YUV sequences for section 12.2."""

from __future__ import annotations

import argparse
import csv
import math
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np


TRAIN_SEQS = ["AcademicBuilding", "EastGate", "Library"]
VALIDATION_SEQS = ["AdministrationBuilding", "SouthGate"]
STRETCH_FACTORS = [1.0, 1.15, 1.41, 2.0, 3.86, 5.0]
LAT_BUCKETS = [(0.0, 30.0, "[0,30)"), (30.0, 60.0, "[30,60)"), (60.0, 75.0, "[60,75)"), (75.0, 90.0001, "[75,90]")]


@dataclass(frozen=True)
class SequenceInfo:
    name: str
    path: Path
    width: int
    height: int
    frames: int
    bitdepth: int


def s_name(s: float) -> str:
    text = f"{s:g}"
    return text.replace(".", "p")


def lat_from_y(y: int, patch_h: int, height: int) -> float:
    center_y = y + 0.5 * patch_h
    return abs((0.5 * height - center_y) * 180.0 / height)


def bucket_name(lat: float) -> str:
    for lo, hi, name in LAT_BUCKETS:
        if lo <= lat < hi:
            return name
    return "unknown"


def read_yuv420_frame(path: Path, width: int, height: int, frame_idx: int, bitdepth: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    bytes_per_sample = 1 if bitdepth <= 8 else 2
    dtype = np.uint8 if bitdepth <= 8 else np.dtype("<u2")
    frame_size = width * height * 3 // 2 * bytes_per_sample
    with path.open("rb") as fh:
        fh.seek(frame_idx * frame_size)
        raw = fh.read(frame_size)
    expected = width * height * 3 // 2
    data = np.frombuffer(raw, dtype=dtype)
    if data.size != expected:
        raise RuntimeError(f"short frame in {path}: got {data.size}, expected {expected}")
    y_size = width * height
    c_w = width // 2
    c_h = height // 2
    y = data[:y_size].reshape(height, width)
    u = data[y_size : y_size + c_w * c_h].reshape(c_h, c_w)
    v = data[y_size + c_w * c_h :].reshape(c_h, c_w)
    return y, u, v


def crop_patch(seq: SequenceInfo, frame_idx: int, x: int, y: int, patch: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    yp, up, vp = read_yuv420_frame(seq.path, seq.width, seq.height, frame_idx, seq.bitdepth)
    return (
        yp[y : y + patch, x : x + patch].copy(),
        up[y // 2 : (y + patch) // 2, x // 2 : (x + patch) // 2].copy(),
        vp[y // 2 : (y + patch) // 2, x // 2 : (x + patch) // 2].copy(),
    )


def stretch_plane_wrap(plane: np.ndarray, s: float) -> np.ndarray:
    if abs(s - 1.0) < 1.0e-12:
        return plane.copy()
    h, w = plane.shape
    center = (w - 1) * 0.5
    x = np.arange(w, dtype=np.float64)
    src = np.mod(center + (x - center) / s, w)
    x0 = np.floor(src).astype(np.int64)
    x1 = (x0 + 1) % w
    t = (src - x0).astype(np.float64)
    out = plane[:, x0].astype(np.float64) * (1.0 - t)[None, :] + plane[:, x1].astype(np.float64) * t[None, :]
    return np.rint(out).clip(0, np.iinfo(plane.dtype).max).astype(plane.dtype)


def stretch_patch(patch: tuple[np.ndarray, np.ndarray, np.ndarray], s: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return tuple(stretch_plane_wrap(p, s) for p in patch)  # type: ignore[return-value]


def list_sequences(root: Path, names: list[str], width: int, height: int, frames: int, bitdepth: int) -> list[SequenceInfo]:
    seqs = []
    for name in names:
        path = root / f"{name}_100f.yuv"
        if not path.exists():
            raise FileNotFoundError(path)
        seqs.append(SequenceInfo(name, path, width, height, frames, bitdepth))
    return seqs


def sample_manifest(split: str, seqs: list[SequenceInfo], rng: random.Random, patch: int, per_bucket: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    even_x = {seq.name: list(range(0, seq.width - patch + 1, 2)) for seq in seqs}
    even_y = {seq.name: list(range(0, seq.height - patch + 1, 2)) for seq in seqs}
    y_by_bucket: dict[str, dict[str, list[int]]] = {name: {} for _, _, name in LAT_BUCKETS}
    for seq in seqs:
        for _, _, bname in LAT_BUCKETS:
            y_by_bucket[bname][seq.name] = [y for y in even_y[seq.name] if bucket_name(lat_from_y(y, patch, seq.height)) == bname]
            if not y_by_bucket[bname][seq.name]:
                raise RuntimeError(f"no y positions for {seq.name} bucket {bname}")

    patch_idx = 0
    for _, _, bname in LAT_BUCKETS:
        for _ in range(per_bucket):
            seq = rng.choice(seqs)
            x = rng.choice(even_x[seq.name])
            y = rng.choice(y_by_bucket[bname][seq.name])
            frame = rng.randrange(seq.frames)
            frame_out = patch_idx // 16
            tile = patch_idx % 16
            tile_x = tile % 4
            tile_y = tile // 4
            lat = lat_from_y(y, patch, seq.height)
            rows.append(
                {
                    "patchIndex": patch_idx,
                    "split": split,
                    "sequence": seq.name,
                    "sourcePath": str(seq.path),
                    "sourceFrame": frame,
                    "sourceX": x,
                    "sourceY": y,
                    "sourceLatitudeDeg": lat,
                    "latitudeBucket": bucket_name(lat),
                    "outFrame": frame_out,
                    "tileX": tile_x,
                    "tileY": tile_y,
                    "outX": tile_x * patch,
                    "outY": tile_y * patch,
                }
            )
            patch_idx += 1
    return rows


def write_manifest(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def load_manifest(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build_sequence(
    rows: list[dict[str, str]],
    s: float,
    out_path: Path,
    width: int,
    height: int,
    source_width: int,
    source_height: int,
    patch: int,
    bitdepth: int,
) -> None:
    dtype = np.uint8 if bitdepth <= 8 else np.dtype("<u2")
    max_frame = max(int(r["outFrame"]) for r in rows)
    seq_cache: dict[tuple[str, int], tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("wb") as fh:
        for frame_idx in range(max_frame + 1):
            y_frame = np.zeros((height, width), dtype=dtype)
            u_frame = np.zeros((height // 2, width // 2), dtype=dtype)
            v_frame = np.zeros((height // 2, width // 2), dtype=dtype)
            frame_rows = [r for r in rows if int(r["outFrame"]) == frame_idx]
            for row in frame_rows:
                seq_key = (row["sourcePath"], int(row["sourceFrame"]))
                if seq_key not in seq_cache:
                    seq_cache[seq_key] = read_yuv420_frame(Path(row["sourcePath"]), source_width, source_height, int(row["sourceFrame"]), bitdepth)
                src_y, src_u, src_v = seq_cache[seq_key]
                x = int(row["sourceX"])
                y = int(row["sourceY"])
                patch_in = (
                    src_y[y : y + patch, x : x + patch].copy(),
                    src_u[y // 2 : (y + patch) // 2, x // 2 : (x + patch) // 2].copy(),
                    src_v[y // 2 : (y + patch) // 2, x // 2 : (x + patch) // 2].copy(),
                )
                py, pu, pv = stretch_patch(patch_in, s)
                ox = int(row["outX"])
                oy = int(row["outY"])
                y_frame[oy : oy + patch, ox : ox + patch] = py
                u_frame[oy // 2 : (oy + patch) // 2, ox // 2 : (ox + patch) // 2] = pu
                v_frame[oy // 2 : (oy + patch) // 2, ox // 2 : (ox + patch) // 2] = pv
            fh.write(y_frame.tobytes())
            fh.write(u_frame.tobytes())
            fh.write(v_frame.tobytes())


def generate(args: argparse.Namespace) -> None:
    split_map = {"train": TRAIN_SEQS, "validation": VALIDATION_SEQS}
    out_dir = args.out_dir
    for split in args.splits:
        rng = random.Random(args.seed + (0 if split == "train" else 100000))
        seqs = list_sequences(args.sequence_root, split_map[split], args.source_width, args.source_height, args.source_frames, args.bitdepth)
        manifest_path = out_dir / "manifests" / f"sjtu_{split}_patch256_manifest.csv"
        if args.reuse_manifest and manifest_path.exists():
            rows = load_manifest(manifest_path)
        else:
            rows_obj = sample_manifest(split, seqs, rng, args.patch, args.per_bucket)
            write_manifest(manifest_path, rows_obj)
            rows = load_manifest(manifest_path)
        for s in args.stretch:
            out_path = out_dir / "sequences" / f"sjtu_{split}_patch256_s{s_name(s)}_512x512_16f.yuv"
            build_sequence(rows, s, out_path, args.out_width, args.out_height, args.source_width, args.source_height, args.patch, args.bitdepth)
            print(out_path)


def self_test(tmp_dir: Path) -> None:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    plane = np.arange(16, dtype=np.uint8).reshape(4, 4)
    assert np.array_equal(stretch_plane_wrap(plane, 1.0), plane)
    impulse = np.zeros((8, 8), dtype=np.uint8)
    impulse[4, 4] = 255
    stretched = stretch_plane_wrap(impulse, 2.0)
    assert stretched[4].sum() > 0
    patch = (np.arange(128 * 128, dtype=np.uint8).reshape(128, 128), np.zeros((64, 64), dtype=np.uint8), np.ones((64, 64), dtype=np.uint8))
    stretched_patch = stretch_patch(patch, 1.0)
    assert all(np.array_equal(a, b) for a, b in zip(patch, stretched_patch))
    out = tmp_dir / "one_frame.yuv"
    rows = [
        {
            "outFrame": "0",
            "sourcePath": "",
            "sourceFrame": "0",
            "sourceX": "0",
            "sourceY": "0",
            "outX": str((i % 4) * 128),
            "outY": str((i // 4) * 128),
        }
        for i in range(16)
    ]
    y_frame = np.zeros((512, 512), dtype=np.uint8)
    u_frame = np.zeros((256, 256), dtype=np.uint8)
    v_frame = np.zeros((256, 256), dtype=np.uint8)
    with out.open("wb") as fh:
        fh.write(y_frame.tobytes())
        fh.write(u_frame.tobytes())
        fh.write(v_frame.tobytes())
    assert out.stat().st_size == 512 * 512 * 3 // 2
    print("self-test ok")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    gen = sub.add_parser("generate")
    gen.add_argument("--sequence-root", type=Path, default=Path(r"I:\SJTU8K360sequence\first100f"))
    gen.add_argument("--out-dir", type=Path, default=Path(r"lahtp_runs\sjtu_patch_stretch_12_2"))
    gen.add_argument("--splits", nargs="+", choices=["train", "validation"], default=["train", "validation"])
    gen.add_argument("--stretch", nargs="+", type=float, default=STRETCH_FACTORS)
    gen.add_argument("--seed", type=int, default=20260524)
    gen.add_argument("--patch", type=int, default=128)
    gen.add_argument("--per-bucket", type=int, default=64)
    gen.add_argument("--source-width", type=int, default=3840)
    gen.add_argument("--source-height", type=int, default=1920)
    gen.add_argument("--source-frames", type=int, default=100)
    gen.add_argument("--out-width", type=int, default=512)
    gen.add_argument("--out-height", type=int, default=512)
    gen.add_argument("--bitdepth", type=int, default=8)
    gen.add_argument("--reuse-manifest", action="store_true")
    gen.set_defaults(func=generate)

    test = sub.add_parser("self-test")
    test.add_argument("--tmp-dir", type=Path, default=Path(r"lahtp_runs\sjtu_patch_stretch_12_2_selftest"))
    test.set_defaults(func=lambda args: self_test(args.tmp_dir))

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
