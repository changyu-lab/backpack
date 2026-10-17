#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.fft import dctn


PATCH_H = 128
PATCH_W0 = 128
TILES_X = 4
TILES_Y = 4
FRAMES = 16
HEIGHT = 512
STRETCHES = ("1", "1.15", "1.41", "2", "3.86", "5")
QPS = (22, 27, 32, 37)
SPLITS = ("train", "validation")


def s_name(s: str | float) -> str:
    return str(s).replace(".", "p")


def patch_width(s: str | float) -> int:
    v = int(round(128 * float(s)))
    return v if v % 2 == 0 else v + 1


def frame_width(s: str | float) -> int:
    return 4 * patch_width(s)


def frame_size(width: int, height: int = HEIGHT) -> int:
    return width * height * 3 // 2


def read_y_frames(path: Path, width: int) -> np.ndarray:
    data = np.fromfile(path, dtype=np.uint8)
    expected = frame_size(width) * FRAMES
    if data.size != expected:
        raise RuntimeError(f"unexpected YUV size for {path}: {data.size}, expected {expected}")
    frames = np.empty((FRAMES, HEIGHT, width), dtype=np.uint8)
    y_size = width * HEIGHT
    fs = frame_size(width)
    for f in range(FRAMES):
        off = f * fs
        frames[f] = data[off : off + y_size].reshape(HEIGHT, width)
    return frames


def decode_if_needed(decoder: Path, bitstream: Path, recon: Path, width: int) -> None:
    expected = frame_size(width) * FRAMES
    if recon.exists() and recon.stat().st_size == expected:
        return
    recon.parent.mkdir(parents=True, exist_ok=True)
    with recon.with_suffix(".decode.log").open("w", encoding="utf-8") as log:
        subprocess.run([str(decoder), "-b", str(bitstream), "-o", str(recon), "-d", "8"], stdout=log, stderr=subprocess.STDOUT, check=True)
    if recon.stat().st_size != expected:
        raise RuntimeError(f"unexpected decoder output size: {recon}")


def dct_patches(input_yuv: Path, recon_yuv: Path, width: int, pw: int) -> np.ndarray:
    inp = read_y_frames(input_yuv, width).astype(np.float32)
    rec = read_y_frames(recon_yuv, width).astype(np.float32)
    coeffs = np.empty((FRAMES * 16, PATCH_H, pw), dtype=np.float32)
    for f in range(FRAMES):
        residual = inp[f] - rec[f]
        for ty in range(TILES_Y):
            for tx in range(TILES_X):
                idx = f * 16 + ty * TILES_X + tx
                patch = residual[ty * PATCH_H : (ty + 1) * PATCH_H, tx * pw : (tx + 1) * pw]
                coeffs[idx] = dctn(patch, type=2, norm="ortho").astype(np.float32)
    return coeffs


class CorrAcc:
    def __init__(self) -> None:
        shape = (PATCH_H, PATCH_W0)
        self.n = 0
        self.sum_x = np.zeros(shape, dtype=np.float64)
        self.sum_y = np.zeros(shape, dtype=np.float64)
        self.sum_x2 = np.zeros(shape, dtype=np.float64)
        self.sum_y2 = np.zeros(shape, dtype=np.float64)
        self.sum_xy = np.zeros(shape, dtype=np.float64)

    def add(self, x: np.ndarray, y: np.ndarray) -> None:
        xx = x[:, :PATCH_W0].astype(np.float64)
        yy = y[:, :PATCH_W0].astype(np.float64)
        self.n += xx.shape[0]
        self.sum_x += xx.sum(axis=0)
        self.sum_y += yy.sum(axis=0)
        self.sum_x2 += (xx * xx).sum(axis=0)
        self.sum_y2 += (yy * yy).sum(axis=0)
        self.sum_xy += (xx * yy).sum(axis=0)

    def corr(self) -> np.ndarray:
        n = float(self.n)
        cov = self.sum_xy - self.sum_x * self.sum_y / n
        vx = self.sum_x2 - self.sum_x * self.sum_x / n
        vy = self.sum_y2 - self.sum_y * self.sum_y / n
        den = np.sqrt(np.maximum(vx, 0.0) * np.maximum(vy, 0.0))
        out = np.full_like(cov, np.nan, dtype=np.float64)
        np.divide(cov, den, out=out, where=den > 0)
        return out


def save_heatmap(corr: np.ndarray, out: Path, title: str, crop: int | None = None) -> None:
    data = corr[:crop, :crop] if crop else corr
    fig, ax = plt.subplots(figsize=(4.2, 3.8), dpi=220)
    im = ax.imshow(data, origin="upper", vmin=-1, vmax=1, cmap="coolwarm", interpolation="nearest")
    ax.set_title(title)
    ax.set_xlabel("u")
    ax.set_ylabel("v")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="corr")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-root", type=Path, required=True)
    ap.add_argument("--decoder", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--keep-recon", action="store_true")
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    recon_dir = args.out_dir / "recon"
    accs = {s: CorrAcc() for s in STRETCHES}

    for split in SPLITS:
        for qp in QPS:
            base_w = frame_width("1")
            base_pw = patch_width("1")
            base_tag = f"{split}_s1_qp{qp}"
            base_seq = args.run_root / "sequences" / f"sjtu_{split}_widepatch256_s1_{base_w}x{HEIGHT}_16f.yuv"
            base_bs = args.run_root / "bin" / f"{base_tag}.266"
            base_rec = recon_dir / f"{base_tag}_rec.yuv"
            decode_if_needed(args.decoder, base_bs, base_rec, base_w)
            base_coeff = dct_patches(base_seq, base_rec, base_w, base_pw)
            for s in STRETCHES:
                pw = patch_width(s)
                fw = frame_width(s)
                tag = f"{split}_s{s_name(s)}_qp{qp}"
                seq = args.run_root / "sequences" / f"sjtu_{split}_widepatch256_s{s_name(s)}_{fw}x{HEIGHT}_16f.yuv"
                bs = args.run_root / "bin" / f"{tag}.266"
                rec = recon_dir / f"{tag}_rec.yuv"
                decode_if_needed(args.decoder, bs, rec, fw)
                cur = base_coeff if s == "1" else dct_patches(seq, rec, fw, pw)
                accs[s].add(cur[:, :, :PATCH_W0], base_coeff)
                print(f"[map] {tag}", flush=True)
                if not args.keep_recon and s != "1":
                    rec.unlink(missing_ok=True)
                    rec.with_suffix(".decode.log").unlink(missing_ok=True)
            if not args.keep_recon:
                base_rec.unlink(missing_ok=True)
                base_rec.with_suffix(".decode.log").unlink(missing_ok=True)

    summary_rows = []
    for s, acc in accs.items():
        corr = acc.corr()
        np.savetxt(args.out_dir / f"freq_corr_map_s{s_name(s)}_128x128.csv", corr, delimiter=",")
        save_heatmap(corr, args.out_dir / f"freq_corr_map_s{s_name(s)}_128x128.png", f"s={s}: frequency-wise corr, left 128x128")
        save_heatmap(corr, args.out_dir / f"freq_corr_map_s{s_name(s)}_32x32.png", f"s={s}: low-frequency corr", crop=32)
        finite = np.isfinite(corr)
        low8 = corr[:8, :8]
        low16 = corr[:16, :16]
        summary_rows.append(
            {
                "StretchS": float(s),
                "SamplesPerFrequency": acc.n,
                "MeanCorrAllFreq": float(np.nanmean(corr[finite])),
                "MedianCorrAllFreq": float(np.nanmedian(corr[finite])),
                "MeanCorrLow8x8": float(np.nanmean(low8)),
                "MeanCorrLow16x16": float(np.nanmean(low16)),
                "MeanCorrLeftHalf": float(np.nanmean(corr[:, :64])),
                "MeanCorrRightHalfOfLeft128": float(np.nanmean(corr[:, 64:128])),
            }
        )
    pd.DataFrame(summary_rows).to_csv(args.out_dir / "freq_corr_map_summary.csv", index=False)


if __name__ == "__main__":
    main()
