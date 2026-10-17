#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.fft import dctn


PATCH_H = 128
PATCH_W0 = 128
TILES_X = 4
TILES_Y = 4
FRAMES_OUT = 16
SOURCE_W = 3840
SOURCE_H = 1920
SOURCE_FRAMES = 100
STRETCHES = ("1", "1.15", "1.41", "2", "3.86", "5")
QPS = (22, 27, 32, 37)
SPLITS = ("train", "validation")


@dataclass(frozen=True)
class Case:
    split: str
    s_label: str
    qp: int

    @property
    def s(self) -> float:
        return float(self.s_label)

    @property
    def s_name(self) -> str:
        return self.s_label.replace(".", "p")

    @property
    def tag(self) -> str:
        return f"{self.split}_s{self.s_name}_qp{self.qp}"


def even_round(x: float) -> int:
    v = int(round(x))
    return v if v % 2 == 0 else v + 1


def patch_width(s: str | float) -> int:
    return even_round(PATCH_W0 * float(s))


def frame_width(s: str | float) -> int:
    return TILES_X * patch_width(s)


def frame_height() -> int:
    return TILES_Y * PATCH_H


def frame_size_yuv420(width: int, height: int) -> int:
    return width * height * 3 // 2


def read_yuv420_frame(path: Path, width: int, height: int, frame_idx: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    frame_size = frame_size_yuv420(width, height)
    with path.open("rb") as fh:
        fh.seek(frame_idx * frame_size)
        y = np.frombuffer(fh.read(width * height), dtype=np.uint8).reshape(height, width).copy()
        u = np.frombuffer(fh.read(width * height // 4), dtype=np.uint8).reshape(height // 2, width // 2).copy()
        v = np.frombuffer(fh.read(width * height // 4), dtype=np.uint8).reshape(height // 2, width // 2).copy()
    return y, u, v


def read_y_frames(path: Path, width: int, height: int, frames: int = FRAMES_OUT) -> np.ndarray:
    frame_size = frame_size_yuv420(width, height)
    data = np.fromfile(path, dtype=np.uint8)
    expected = frame_size * frames
    if data.size != expected:
        raise RuntimeError(f"unexpected YUV size for {path}: {data.size}, expected {expected}")
    out = np.empty((frames, height, width), dtype=np.uint8)
    for f in range(frames):
        off = f * frame_size
        out[f] = data[off : off + width * height].reshape(height, width)
    return out


def stretch_plane_wide(src: np.ndarray, out_w: int, s: float) -> np.ndarray:
    if out_w == src.shape[1] and abs(s - 1.0) < 1e-12:
        return src.copy()
    h, in_w = src.shape
    out = np.empty((h, out_w), dtype=np.uint8)
    src_c = 0.5 * (in_w - 1)
    out_c = 0.5 * (out_w - 1)
    xs = src_c + (np.arange(out_w, dtype=np.float64) - out_c) / s
    xs = np.clip(xs, 0.0, in_w - 1.0)
    x0 = np.floor(xs).astype(np.int64)
    x1 = np.minimum(x0 + 1, in_w - 1)
    a = xs - x0
    for y in range(h):
        vals = (1.0 - a) * src[y, x0].astype(np.float64) + a * src[y, x1].astype(np.float64)
        out[y] = np.clip(np.rint(vals), 0, 255).astype(np.uint8)
    return out


def build_wide_sequences(run_root: Path, out_root: Path, splits: list[str], stretches: list[str]) -> None:
    out_seq = out_root / "sequences"
    out_seq.mkdir(parents=True, exist_ok=True)
    for split in splits:
        manifest = pd.read_csv(run_root / "manifests" / f"sjtu_{split}_patch256_manifest.csv")
        for s_label in stretches:
            s = float(s_label)
            pw = patch_width(s_label)
            fw = frame_width(s_label)
            fh = frame_height()
            out_path = out_seq / f"sjtu_{split}_widepatch256_s{s_label.replace('.', 'p')}_{fw}x{fh}_16f.yuv"
            if out_path.exists() and out_path.stat().st_size == frame_size_yuv420(fw, fh) * FRAMES_OUT:
                print(f"[skip-seq] {out_path}", flush=True)
                continue
            cache: dict[tuple[str, int], tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
            with out_path.open("wb") as fh_out:
                for frame_idx in range(FRAMES_OUT):
                    y_frame = np.zeros((fh, fw), dtype=np.uint8)
                    u_frame = np.zeros((fh // 2, fw // 2), dtype=np.uint8)
                    v_frame = np.zeros((fh // 2, fw // 2), dtype=np.uint8)
                    frame_rows = manifest[manifest["outFrame"] == frame_idx]
                    for _, row in frame_rows.iterrows():
                        key = (str(row["sourcePath"]), int(row["sourceFrame"]))
                        if key not in cache:
                            cache[key] = read_yuv420_frame(Path(key[0]), SOURCE_W, SOURCE_H, key[1])
                        sy, su, sv = cache[key]
                        x = int(row["sourceX"])
                        y = int(row["sourceY"])
                        patch_y = sy[y : y + PATCH_H, x : x + PATCH_W0]
                        patch_u = su[y // 2 : (y + PATCH_H) // 2, x // 2 : (x + PATCH_W0) // 2]
                        patch_v = sv[y // 2 : (y + PATCH_H) // 2, x // 2 : (x + PATCH_W0) // 2]
                        wy = stretch_plane_wide(patch_y, pw, s)
                        wu = stretch_plane_wide(patch_u, pw // 2, s)
                        wv = stretch_plane_wide(patch_v, pw // 2, s)
                        tx = int(row["tileX"])
                        ty = int(row["tileY"])
                        ox = tx * pw
                        oy = ty * PATCH_H
                        y_frame[oy : oy + PATCH_H, ox : ox + pw] = wy
                        u_frame[oy // 2 : (oy + PATCH_H) // 2, ox // 2 : (ox + pw) // 2] = wu
                        v_frame[oy // 2 : (oy + PATCH_H) // 2, ox // 2 : (ox + pw) // 2] = wv
                    fh_out.write(y_frame.tobytes())
                    fh_out.write(u_frame.tobytes())
                    fh_out.write(v_frame.tobytes())
            print(f"[seq] {out_path}", flush=True)


def run_encodes(out_root: Path, encoder: Path, splits: list[str], stretches: list[str], qps: list[int]) -> None:
    (out_root / "bin").mkdir(parents=True, exist_ok=True)
    (out_root / "logs").mkdir(parents=True, exist_ok=True)
    summary_path = out_root / "encode_summary.csv"
    done = set()
    if summary_path.exists():
        with summary_path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                done.add((row["split"], row["s"], int(row["qp"])))
    else:
        summary_path.write_text("split,s,qp,input,bitstream,log,seconds\n", encoding="utf-8")
    for split in splits:
        for s_label in stretches:
            fw = frame_width(s_label)
            fh = frame_height()
            seq = out_root / "sequences" / f"sjtu_{split}_widepatch256_s{s_label.replace('.', 'p')}_{fw}x{fh}_16f.yuv"
            for qp in qps:
                case = Case(split, s_label, qp)
                bitstream = out_root / "bin" / f"{case.tag}.266"
                log = out_root / "logs" / f"{case.tag}.log"
                if (split, s_label, qp) in done and bitstream.exists() and bitstream.stat().st_size > 0:
                    print(f"[skip-enc] {case.tag}", flush=True)
                    continue
                print(f"[encode] {case.tag} {fw}x{fh}", flush=True)
                import time

                start = time.time()
                with log.open("w", encoding="utf-8") as fh_log:
                    subprocess.run(
                        [
                            str(encoder),
                            "--preset",
                            "medium",
                            "-i",
                            str(seq),
                            "-s",
                            f"{fw}x{fh}",
                            "-r",
                            "30",
                            "-c",
                            "yuv420",
                            "-q",
                            str(qp),
                            "--qpa",
                            "0",
                            "-f",
                            str(FRAMES_OUT),
                            "-ip",
                            "1",
                            "--mtprofile",
                            "0",
                            "--threads",
                            "1",
                            "--additional",
                            "LardLfnstSkip=0",
                            "-o",
                            str(bitstream),
                        ],
                        stdout=fh_log,
                        stderr=subprocess.STDOUT,
                        check=True,
                    )
                seconds = int(round(time.time() - start))
                with summary_path.open("a", encoding="utf-8") as summary_fh:
                    summary_fh.write(f"{split},{s_label},{qp},{seq},{bitstream},{log},{seconds}\n")


def decode_if_needed(decoder: Path, bitstream: Path, recon: Path, width: int, height: int) -> None:
    expected = frame_size_yuv420(width, height) * FRAMES_OUT
    if recon.exists() and recon.stat().st_size == expected:
        return
    recon.parent.mkdir(parents=True, exist_ok=True)
    log = recon.with_suffix(".decode.log")
    with log.open("w", encoding="utf-8") as fh:
        subprocess.run([str(decoder), "-b", str(bitstream), "-o", str(recon), "-d", "8"], stdout=fh, stderr=subprocess.STDOUT, check=True)
    if recon.stat().st_size != expected:
        raise RuntimeError(f"unexpected decoder output size for {recon}: {recon.stat().st_size}, expected {expected}")


def pearson(a: np.ndarray, b: np.ndarray) -> float:
    aa = a.astype(np.float64).ravel()
    bb = b.astype(np.float64).ravel()
    aa -= aa.mean()
    bb -= bb.mean()
    den = math.sqrt(float(np.dot(aa, aa) * np.dot(bb, bb)))
    return float(np.dot(aa, bb) / den) if den > 0 else math.nan


def patch_dcts(input_yuv: Path, recon_yuv: Path, width: int, patch_w: int) -> np.ndarray:
    inp = read_y_frames(input_yuv, width, frame_height()).astype(np.float32)
    rec = read_y_frames(recon_yuv, width, frame_height()).astype(np.float32)
    coeffs = np.empty((FRAMES_OUT * 16, PATCH_H, patch_w), dtype=np.float32)
    for f in range(FRAMES_OUT):
        residual = inp[f] - rec[f]
        for ty in range(TILES_Y):
            for tx in range(TILES_X):
                idx = f * 16 + ty * 4 + tx
                patch = residual[ty * PATCH_H : (ty + 1) * PATCH_H, tx * patch_w : (tx + 1) * patch_w]
                coeffs[idx] = dctn(patch, type=2, norm="ortho").astype(np.float32)
    return coeffs


def load_manifest_lat(run_root: Path, split: str) -> pd.DataFrame:
    return pd.read_csv(run_root / "manifests" / f"sjtu_{split}_patch256_manifest.csv").set_index("patchIndex", drop=False)


def analyze_residual_spectrum(source_run_root: Path, out_root: Path, decoder: Path, splits: list[str], stretches: list[str], qps: list[int], keep_recon: bool) -> None:
    rows: list[dict[str, object]] = []
    recon_dir = out_root / "recon"
    for split in splits:
        manifest = load_manifest_lat(source_run_root, split)
        for qp in qps:
            base_w = frame_width("1")
            base_pw = patch_width("1")
            base_case = Case(split, "1", qp)
            base_seq = out_root / "sequences" / f"sjtu_{split}_widepatch256_s1_{base_w}x{frame_height()}_16f.yuv"
            base_bs = out_root / "bin" / f"{base_case.tag}.266"
            base_rec = recon_dir / f"{base_case.tag}_rec.yuv"
            decode_if_needed(decoder, base_bs, base_rec, base_w, frame_height())
            base_coeff = patch_dcts(base_seq, base_rec, base_w, base_pw)
            for s_label in stretches:
                case = Case(split, s_label, qp)
                pw = patch_width(s_label)
                fw = frame_width(s_label)
                seq = out_root / "sequences" / f"sjtu_{split}_widepatch256_s{case.s_name}_{fw}x{frame_height()}_16f.yuv"
                bs = out_root / "bin" / f"{case.tag}.266"
                rec = recon_dir / f"{case.tag}_rec.yuv"
                decode_if_needed(decoder, bs, rec, fw, frame_height())
                coeff = base_coeff if s_label == "1" else patch_dcts(seq, rec, fw, pw)
                for pidx in range(FRAMES_OUT * 16):
                    ref = base_coeff[pidx]
                    cur = coeff[pidx]
                    left128 = cur[:, :PATCH_W0]
                    total_energy = float(np.sum(cur.astype(np.float64) ** 2))
                    left_energy = float(np.sum(left128.astype(np.float64) ** 2))
                    man = manifest.loc[pidx]
                    rows.append(
                        {
                            "Split": split,
                            "StretchS": float(s_label),
                            "PatchWidth": pw,
                            "FrameWidth": fw,
                            "QP": qp,
                            "PatchIndex": pidx,
                            "LatitudeBucket": man["latitudeBucket"],
                            "SourceSequence": man["sequence"],
                            "SourceFrame": int(man["sourceFrame"]),
                            "SourceX": int(man["sourceX"]),
                            "SourceY": int(man["sourceY"]),
                            "CorrLeft128x128": pearson(ref, left128),
                            "CorrLeftLow8x8": pearson(ref[:8, :8], left128[:8, :8]),
                            "CorrLeftLow16x16": pearson(ref[:16, :16], left128[:16, :16]),
                            "Left128EnergyRatio": left_energy / (total_energy + 1e-12),
                            "BeyondLeft128EnergyRatio": 1.0 - left_energy / (total_energy + 1e-12),
                            "EnergyRatio_s_over_s1": total_energy / (float(np.sum(ref.astype(np.float64) ** 2)) + 1e-12),
                        }
                    )
                print(f"[analyze] {case.tag}", flush=True)
                if not keep_recon and s_label != "1":
                    rec.unlink(missing_ok=True)
                    rec.with_suffix(".decode.log").unlink(missing_ok=True)
            if not keep_recon:
                base_rec.unlink(missing_ok=True)
                base_rec.with_suffix(".decode.log").unlink(missing_ok=True)

    df = pd.DataFrame(rows)
    df.to_csv(out_root / "table_wide_residual_dct_corr_by_patch.csv", index=False)
    summary = (
        df.groupby(["Split", "StretchS", "QP", "LatitudeBucket"], dropna=False)
        .agg(
            Samples=("PatchIndex", "count"),
            PatchWidth=("PatchWidth", "first"),
            MeanCorrLeft128x128=("CorrLeft128x128", "mean"),
            MedianCorrLeft128x128=("CorrLeft128x128", "median"),
            MeanCorrLeftLow8x8=("CorrLeftLow8x8", "mean"),
            MeanCorrLeftLow16x16=("CorrLeftLow16x16", "mean"),
            MeanLeft128EnergyRatio=("Left128EnergyRatio", "mean"),
            MeanBeyondLeft128EnergyRatio=("BeyondLeft128EnergyRatio", "mean"),
            MeanEnergyRatio_s_over_s1=("EnergyRatio_s_over_s1", "mean"),
        )
        .reset_index()
    )
    summary.to_csv(out_root / "table_wide_residual_dct_corr_summary.csv", index=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-run-root", type=Path, required=True, help="Existing fixed-patch run root containing manifests.")
    ap.add_argument("--out-root", type=Path, required=True)
    ap.add_argument("--encoder", type=Path, required=True)
    ap.add_argument("--decoder", type=Path, required=True)
    ap.add_argument("--splits", nargs="+", choices=SPLITS, default=list(SPLITS))
    ap.add_argument("--stretches", nargs="+", default=list(STRETCHES))
    ap.add_argument("--qps", nargs="+", type=int, default=list(QPS))
    ap.add_argument("--generate-only", action="store_true")
    ap.add_argument("--encode-only", action="store_true")
    ap.add_argument("--analyze-only", action="store_true")
    ap.add_argument("--keep-recon", action="store_true")
    args = ap.parse_args()
    args.out_root.mkdir(parents=True, exist_ok=True)

    if not args.encode_only and not args.analyze_only:
        build_wide_sequences(args.source_run_root, args.out_root, args.splits, args.stretches)
    if args.generate_only:
        return
    if not args.generate_only and not args.analyze_only:
        run_encodes(args.out_root, args.encoder, args.splits, args.stretches, args.qps)
    if args.encode_only:
        return
    analyze_residual_spectrum(args.source_run_root, args.out_root, args.decoder, args.splits, args.stretches, args.qps, args.keep_recon)
    (args.out_root / "wide_residual_spectrum_report.md").write_text(
        "# Wide Patch Residual Spectrum Experiment\n\n"
        "Patch output width is `even(round(128*s))`, preserving YUV420 compatibility. "
        "Each frame is a 4x4 mosaic, so frame width is `4*patch_width`. "
        "The residual is `input_y - reconstructed_y`; each patch residual is transformed by an orthonormal 2D DCT. "
        "`s>1` coefficients are compared against `s=1` using the left `128x128` coefficient block.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
