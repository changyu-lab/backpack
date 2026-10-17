#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.fft import dctn


STRETCHES = ("1", "1.15", "1.41", "2", "3.86", "5")
QPS = (22, 27, 32, 37)
SPLITS = ("train", "validation")
PATCH = 128
WIDTH = 512
HEIGHT = 512
FRAMES = 16
Y_SIZE = WIDTH * HEIGHT
FRAME_SIZE = WIDTH * HEIGHT * 3 // 2


def s_name(s: str | float) -> str:
    return str(s).replace(".", "p")


def parse_final_case(path: Path) -> tuple[str, str, int]:
    m = re.search(r"(train|validation)_s([0-9p.]+)_qp(\d+)\.csv\.final\.csv$", path.name, re.I)
    if not m:
        raise RuntimeError(f"bad final trace name: {path}")
    return m.group(1).lower(), m.group(2).replace("p", "."), int(m.group(3))


def patch_index_from_xy(poc: np.ndarray, x: np.ndarray, y: np.ndarray, w: np.ndarray, h: np.ndarray) -> np.ndarray:
    tile_x = np.clip(((x + 0.5 * w) // PATCH).astype(np.int64), 0, 3)
    tile_y = np.clip(((y + 0.5 * h) // PATCH).astype(np.int64), 0, 3)
    return poc.astype(np.int64) * 16 + tile_y * 4 + tile_x


def size_group_from_area(area: pd.Series, mn: pd.Series, mx: pd.Series) -> pd.Series:
    out = np.full(len(area), "area_large", dtype=object)
    out[area <= 1024] = "area_1024"
    out[area <= 256] = "area_256"
    out[area <= 64] = "area_64"
    out[area <= 32] = "area_32"
    out[area <= 16] = "area_16"
    out[(area > 1024) & (mx >= 4 * mn)] = "area_long"
    return pd.Series(out, index=area.index)


def mode_group_from_mode(mode: pd.Series) -> pd.Series:
    out = np.full(len(mode), "g5_ang_51_plus", dtype=object)
    out[mode <= 50] = "g4_ang_35_50"
    out[mode <= 34] = "g3_ang_18_34"
    out[mode <= 17] = "g2_ang_2_17"
    out[mode == 1] = "g1_dc"
    out[mode == 0] = "g0_planar"
    out[mode < 0] = "non_intra"
    return pd.Series(out, index=mode.index)


def load_manifest(run_root: Path) -> dict[str, pd.DataFrame]:
    out = {}
    for split in SPLITS:
        path = run_root / "manifests" / f"sjtu_{split}_patch256_manifest.csv"
        df = pd.read_csv(path)
        out[split] = df.set_index("patchIndex", drop=False)
    return out


def js_div(p: np.ndarray, q: np.ndarray) -> float:
    eps = 1e-12
    pp = p / (p.sum() + eps)
    qq = q / (q.sum() + eps)
    m = 0.5 * (pp + qq)
    return float(0.5 * np.sum(pp * (np.log(pp + eps) - np.log(m + eps))) + 0.5 * np.sum(qq * (np.log(qq + eps) - np.log(m + eps))))


def pearson(a: np.ndarray, b: np.ndarray) -> float:
    aa = a.astype(np.float64).ravel()
    bb = b.astype(np.float64).ravel()
    aa -= aa.mean()
    bb -= bb.mean()
    den = math.sqrt(float(np.dot(aa, aa) * np.dot(bb, bb)))
    return float(np.dot(aa, bb) / den) if den > 0 else math.nan


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    cols = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def q1_decision_analysis(run_root: Path, out_dir: Path) -> dict[str, int]:
    manifests = load_manifest(run_root)
    final_files = sorted((run_root / "traces").glob("*_s*_qp*.csv.final.csv"))
    patch_rows: list[dict[str, object]] = []
    size_cols = ["area_16", "area_32", "area_64", "area_256", "area_1024", "area_large", "area_long"]
    mode_cols = ["g0_planar", "g1_dc", "g2_ang_2_17", "g3_ang_18_34", "g4_ang_35_50", "g5_ang_51_plus", "non_intra"]

    for path in final_files:
        split, s, qp = parse_final_case(path)
        df = pd.read_csv(path)
        df = df[df["predMode"] == 1].copy()
        if df.empty:
            continue
        area = df["w"] * df["h"]
        df["PatchIndex"] = patch_index_from_xy(df["poc"].to_numpy(), df["x"].to_numpy(), df["y"].to_numpy(), df["w"].to_numpy(), df["h"].to_numpy())
        df["BlockSizeGroup"] = size_group_from_area(area, np.minimum(df["w"], df["h"]), np.maximum(df["w"], df["h"]))
        df["ModeGroup"] = mode_group_from_mode(df["intraMode"])
        df["Area"] = area
        for pidx, g in df.groupby("PatchIndex", sort=False):
            man = manifests[split].loc[int(pidx)]
            row: dict[str, object] = {
                "Split": split,
                "StretchS": float(s),
                "QP": qp,
                "PatchIndex": int(pidx),
                "LatitudeBucket": man["latitudeBucket"],
                "SourceSequence": man["sequence"],
                "SourceFrame": int(man["sourceFrame"]),
                "SourceX": int(man["sourceX"]),
                "SourceY": int(man["sourceY"]),
                "CUCount": int(len(g)),
                "MeanCUAreaByCount": float(g["Area"].mean()),
                "MeanCUAreaByCoverage": float((g["Area"] * g["Area"]).sum() / g["Area"].sum()),
                "DominantSizeByArea": str(g.groupby("BlockSizeGroup")["Area"].sum().idxmax()),
                "DominantModeGroupByArea": str(g.groupby("ModeGroup")["Area"].sum().idxmax()),
                "DominantIntraModeByArea": int(g.groupby("intraMode")["Area"].sum().idxmax()),
                "LFNSTAreaRatio": float(g.loc[g["lfnstIdx"] > 0, "Area"].sum() / max(1.0, float(g["Area"].sum()))),
            }
            total_area = float(g["Area"].sum())
            for c in size_cols:
                row[f"SizeArea_{c}"] = float(g.loc[g["BlockSizeGroup"] == c, "Area"].sum() / total_area)
                row[f"SizeCount_{c}"] = float((g["BlockSizeGroup"] == c).mean())
            for c in mode_cols:
                row[f"ModeArea_{c}"] = float(g.loc[g["ModeGroup"] == c, "Area"].sum() / total_area)
                row[f"ModeCount_{c}"] = float((g["ModeGroup"] == c).mean())
            patch_rows.append(row)

    write_csv(out_dir / "table_q1_decision_by_patch.csv", patch_rows)
    by_key = {(r["Split"], r["QP"], r["PatchIndex"], r["StretchS"]): r for r in patch_rows}
    change_rows: list[dict[str, object]] = []
    for r in patch_rows:
        if float(r["StretchS"]) == 1.0:
            continue
        base = by_key.get((r["Split"], r["QP"], r["PatchIndex"], 1.0))
        if not base:
            continue
        size_p = np.asarray([float(r[f"SizeArea_{c}"]) for c in size_cols])
        size_q = np.asarray([float(base[f"SizeArea_{c}"]) for c in size_cols])
        mode_p = np.asarray([float(r[f"ModeArea_{c}"]) for c in mode_cols])
        mode_q = np.asarray([float(base[f"ModeArea_{c}"]) for c in mode_cols])
        change_rows.append(
            {
                "Split": r["Split"],
                "StretchS": r["StretchS"],
                "QP": r["QP"],
                "PatchIndex": r["PatchIndex"],
                "LatitudeBucket": r["LatitudeBucket"],
                "CUCount_s1": base["CUCount"],
                "CUCount_s": r["CUCount"],
                "DeltaCUCount": int(r["CUCount"]) - int(base["CUCount"]),
                "MeanCUArea_s1": base["MeanCUAreaByCount"],
                "MeanCUArea_s": r["MeanCUAreaByCount"],
                "DeltaMeanCUArea": float(r["MeanCUAreaByCount"]) - float(base["MeanCUAreaByCount"]),
                "SizeAreaJS": js_div(size_p, size_q),
                "ModeGroupAreaJS": js_div(mode_p, mode_q),
                "DominantSizeChanged": int(r["DominantSizeByArea"] != base["DominantSizeByArea"]),
                "DominantModeGroupChanged": int(r["DominantModeGroupByArea"] != base["DominantModeGroupByArea"]),
                "DominantIntraModeChanged": int(r["DominantIntraModeByArea"] != base["DominantIntraModeByArea"]),
                "LFNSTAreaRatio_s1": base["LFNSTAreaRatio"],
                "LFNSTAreaRatio_s": r["LFNSTAreaRatio"],
            }
        )

    write_csv(out_dir / "table_q1_decision_change_vs_s1_by_patch.csv", change_rows)
    summary = (
        pd.DataFrame(change_rows)
        .groupby(["Split", "StretchS", "QP", "LatitudeBucket"], dropna=False)
        .agg(
            Samples=("PatchIndex", "count"),
            MeanDeltaCUCount=("DeltaCUCount", "mean"),
            MeanDeltaMeanCUArea=("DeltaMeanCUArea", "mean"),
            MeanSizeAreaJS=("SizeAreaJS", "mean"),
            MeanModeGroupAreaJS=("ModeGroupAreaJS", "mean"),
            DominantSizeChangeRatio=("DominantSizeChanged", "mean"),
            DominantModeGroupChangeRatio=("DominantModeGroupChanged", "mean"),
            DominantIntraModeChangeRatio=("DominantIntraModeChanged", "mean"),
            MeanLFNSTAreaRatio_s1=("LFNSTAreaRatio_s1", "mean"),
            MeanLFNSTAreaRatio_s=("LFNSTAreaRatio_s", "mean"),
        )
        .reset_index()
    )
    summary.to_csv(out_dir / "table_q1_decision_change_summary.csv", index=False)
    return {"final_files": len(final_files), "patch_rows": len(patch_rows), "change_rows": len(change_rows)}


def read_y_frames(path: Path) -> np.ndarray:
    data = np.fromfile(path, dtype=np.uint8)
    if data.size != FRAME_SIZE * FRAMES:
        raise RuntimeError(f"unexpected yuv size for {path}: {data.size}")
    frames = []
    for f in range(FRAMES):
        off = f * FRAME_SIZE
        frames.append(data[off : off + Y_SIZE].reshape(HEIGHT, WIDTH))
    return np.stack(frames, axis=0)


def patch_dct_coeffs(orig_yuv: Path, rec_yuv: Path) -> np.ndarray:
    org = read_y_frames(orig_yuv).astype(np.float32)
    rec = read_y_frames(rec_yuv).astype(np.float32)
    coeffs = np.empty((FRAMES * 16, PATCH, PATCH), dtype=np.float32)
    for frame in range(FRAMES):
        residual = org[frame] - rec[frame]
        for tile_y in range(4):
            for tile_x in range(4):
                idx = frame * 16 + tile_y * 4 + tile_x
                patch = residual[tile_y * PATCH : (tile_y + 1) * PATCH, tile_x * PATCH : (tile_x + 1) * PATCH]
                coeffs[idx] = dctn(patch, type=2, norm="ortho").astype(np.float32)
    return coeffs


def decode_if_needed(decoder: Path, bitstream: Path, recon: Path) -> None:
    if recon.exists() and recon.stat().st_size == FRAME_SIZE * FRAMES:
        return
    recon.parent.mkdir(parents=True, exist_ok=True)
    log = recon.with_suffix(".decode.log")
    with log.open("w", encoding="utf-8") as fh:
        subprocess.run([str(decoder), "-b", str(bitstream), "-o", str(recon), "-d", "8"], stdout=fh, stderr=subprocess.STDOUT, check=True)
    if recon.stat().st_size != FRAME_SIZE * FRAMES:
        raise RuntimeError(f"decoder output has unexpected size: {recon}")


def q2_spectrum_corr(run_root: Path, out_dir: Path, decoder: Path, keep_recon: bool) -> dict[str, int]:
    manifests = load_manifest(run_root)
    rows: list[dict[str, object]] = []
    recon_dir = out_dir / "recon"
    for split in SPLITS:
        for qp in QPS:
            base_tag = f"{split}_s1_qp{qp}"
            base_org = run_root / "sequences" / f"sjtu_{split}_patch256_s1_512x512_16f.yuv"
            base_bs = run_root / "bin" / f"{base_tag}.266"
            base_rec = recon_dir / f"{base_tag}_rec.yuv"
            decode_if_needed(decoder, base_bs, base_rec)
            base_coeff = patch_dct_coeffs(base_org, base_rec)
            for s in STRETCHES:
                tag = f"{split}_s{s_name(s)}_qp{qp}"
                org = run_root / "sequences" / f"sjtu_{split}_patch256_s{s_name(s)}_512x512_16f.yuv"
                bs = run_root / "bin" / f"{tag}.266"
                rec = recon_dir / f"{tag}_rec.yuv"
                decode_if_needed(decoder, bs, rec)
                coeff = base_coeff if s == "1" else patch_dct_coeffs(org, rec)
                for pidx in range(FRAMES * 16):
                    man = manifests[split].loc[pidx]
                    a = base_coeff[pidx]
                    b = coeff[pidx]
                    rows.append(
                        {
                            "Split": split,
                            "StretchS": float(s),
                            "QP": qp,
                            "PatchIndex": pidx,
                            "LatitudeBucket": man["latitudeBucket"],
                            "CorrFull128x128": pearson(a, b),
                            "CorrLow8x8": pearson(a[:8, :8], b[:8, :8]),
                            "CorrLow16x16": pearson(a[:16, :16], b[:16, :16]),
                            "CorrLeftHalf128x64": pearson(a[:, :64], b[:, :64]),
                            "CorrRightHalf128x64": pearson(a[:, 64:], b[:, 64:]),
                            "EnergyFull_s1": float(np.sum(a.astype(np.float64) ** 2)),
                            "EnergyFull_s": float(np.sum(b.astype(np.float64) ** 2)),
                        }
                    )
                if not keep_recon and s != "1":
                    rec.unlink(missing_ok=True)
                    rec.with_suffix(".decode.log").unlink(missing_ok=True)
            if not keep_recon:
                base_rec.unlink(missing_ok=True)
                base_rec.with_suffix(".decode.log").unlink(missing_ok=True)

    write_csv(out_dir / "table_q2_residual_dct_corr_by_patch.csv", rows)
    df = pd.DataFrame(rows)
    summary = (
        df.groupby(["Split", "StretchS", "QP", "LatitudeBucket"], dropna=False)
        .agg(
            Samples=("PatchIndex", "count"),
            MeanCorrFull128x128=("CorrFull128x128", "mean"),
            MedianCorrFull128x128=("CorrFull128x128", "median"),
            MeanCorrLow8x8=("CorrLow8x8", "mean"),
            MeanCorrLow16x16=("CorrLow16x16", "mean"),
            MeanCorrLeftHalf128x64=("CorrLeftHalf128x64", "mean"),
            MeanCorrRightHalf128x64=("CorrRightHalf128x64", "mean"),
            MeanEnergyRatio_s_over_s1=("EnergyFull_s", lambda x: float(np.mean(x.to_numpy() / df.loc[x.index, "EnergyFull_s1"].to_numpy()))),
        )
        .reset_index()
    )
    summary.to_csv(out_dir / "table_q2_residual_dct_corr_summary.csv", index=False)
    return {"patch_rows": len(rows)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-root", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--decoder", type=Path, default=Path("/root/VTM-23.0-rc360-server/bin/DecoderAppStatic"))
    ap.add_argument("--skip-q1", action="store_true")
    ap.add_argument("--skip-q2", action="store_true")
    ap.add_argument("--keep-recon", action="store_true")
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    if not args.skip_q1:
        result["q1"] = q1_decision_analysis(args.run_root, args.out_dir)
    if not args.skip_q2:
        result["q2"] = q2_spectrum_corr(args.run_root, args.out_dir, args.decoder, args.keep_recon)
    (args.out_dir / "decision_spectrum_validation_report.md").write_text(
        "# Controlled Stretch Decision and Residual Spectrum Validation\n\n"
        f"`{result}`\n\n"
        "Q1 compares final CU partition and intra-mode decisions for the same patch sample against s=1.\n"
        "Q2 decodes the bitstreams, computes Y residual as input minus reconstructed luma, applies an orthonormal 128x128 DCT per patch, and correlates coefficient matrices with the same patch at s=1.\n",
        encoding="utf-8",
    )
    print(result)


if __name__ == "__main__":
    main()
