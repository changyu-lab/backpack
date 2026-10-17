#!/usr/bin/env python3
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def linear_fit(x, y):
    slope, intercept = np.polyfit(x, y, 1)
    pred = intercept + slope * x
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0.0 else np.nan
    rmse = float(np.sqrt(np.mean((y - pred) ** 2)))
    return intercept, slope, pred, r2, rmse


def main():
    parser = argparse.ArgumentParser(description="Plot ln(BPP)/QP vs frame Ieff.")
    parser.add_argument("--input", default="experiments/rc360_frame_model/data/qp17_50_5f/frame_samples.csv")
    parser.add_argument("--output-dir", default="experiments/rc360_frame_model/results_qp17_50_5f/logbpp_div_qp_ieff")
    parser.add_argument("--include-i", action="store_true", help="Include I frames. Default keeps P frames only.")
    args = parser.parse_args()

    root = repo_root()
    input_csv = Path(args.input)
    if not input_csv.is_absolute():
        input_csv = root / input_csv
    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    by_seq_dir = out_dir / "by_sequence"
    by_seq_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(input_csv)
    df["bpp"] = pd.to_numeric(df["actual_bits"], errors="coerce") / (
        pd.to_numeric(df["width"], errors="coerce") * pd.to_numeric(df["height"], errors="coerce")
    )
    df["log_bpp"] = np.log(df["bpp"])
    df["command_qp"] = pd.to_numeric(df["command_qp"], errors="coerce")
    df["ieff_raw"] = pd.to_numeric(df["ieff_raw"], errors="coerce")
    df["poc"] = pd.to_numeric(df["poc"], errors="coerce")
    df["log_bpp_div_qp"] = df["log_bpp"] / df["command_qp"]

    numeric = ["poc", "command_qp", "bpp", "log_bpp", "log_bpp_div_qp", "ieff_raw"]
    df = df[
        np.isfinite(df[numeric]).all(axis=1)
        & (df["bpp"] > 0)
        & (df["command_qp"] > 0)
        & (df["ieff_raw"] > 0)
    ].copy()
    if not args.include_i:
        df = df[(df["poc"] % 8) != 0].copy()

    rows = []
    for sequence, g in df.groupby("sequence"):
        x = g["ieff_raw"].to_numpy(dtype=float)
        y = g["log_bpp_div_qp"].to_numpy(dtype=float)
        intercept, slope, pred, r2, rmse = linear_fit(x, y)
        pearson = float(pd.Series(x).corr(pd.Series(y), method="pearson"))
        spearman = float(pd.Series(x).corr(pd.Series(y), method="spearman"))
        rows.append({
            "sequence": sequence,
            "sample_count": len(g),
            "target": "ln(BPP)/command_qp",
            "target_min": float(np.min(y)),
            "target_mean": float(np.mean(y)),
            "target_max": float(np.max(y)),
            "ieff_min": float(np.min(x)),
            "ieff_mean": float(np.mean(x)),
            "ieff_max": float(np.max(x)),
            "pearson_target_ieff": pearson,
            "spearman_target_ieff": spearman,
            "linear_intercept": intercept,
            "linear_slope": slope,
            "linear_R2": r2,
            "linear_RMSE": rmse,
        })

        fit_x = np.linspace(float(np.min(x)), float(np.max(x)), 200)
        fit_y = intercept + slope * fit_x
        plt.figure(figsize=(8, 5))
        sc = plt.scatter(g["ieff_raw"], g["log_bpp_div_qp"], c=g["command_qp"], cmap="viridis",
                         s=26, alpha=0.68)
        plt.plot(fit_x, fit_y, color="tab:red", linewidth=1.8, label=f"linear fit, R2={r2:.3f}")
        plt.axhline(0.0, color="black", linewidth=1.0)
        plt.xlabel("Frame Ieff (mean of CTU Ieff)")
        plt.ylabel("ln(BPP) / command QP")
        plt.title(f"{sequence}: ln(BPP)/QP vs Ieff")
        plt.grid(True, alpha=0.25)
        plt.legend()
        cbar = plt.colorbar(sc)
        cbar.set_label("Command QP")
        plt.tight_layout()
        plt.savefig(by_seq_dir / f"{sequence}_logbpp_div_qp_vs_ieff.png", dpi=170)
        plt.close()

    pd.DataFrame(rows).to_csv(out_dir / "logbpp_div_qp_ieff_stats.csv", index=False)
    df.to_csv(out_dir / "frame_logbpp_div_qp_samples.csv", index=False)

    plt.figure(figsize=(9, 6))
    for sequence, g in df.groupby("sequence"):
        plt.scatter(g["ieff_raw"], g["log_bpp_div_qp"], s=18, alpha=0.5, label=sequence)
    plt.axhline(0.0, color="black", linewidth=1.0)
    plt.xlabel("Frame Ieff (mean of CTU Ieff)")
    plt.ylabel("ln(BPP) / command QP")
    plt.title("All sequences: ln(BPP)/QP vs Ieff")
    plt.grid(True, alpha=0.25)
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(out_dir / "all_sequences_logbpp_div_qp_vs_ieff.png", dpi=170)
    plt.close()

    print(f"samples={len(df)}")
    print(f"stats={out_dir / 'logbpp_div_qp_ieff_stats.csv'}")
    print(f"samples_csv={out_dir / 'frame_logbpp_div_qp_samples.csv'}")
    print(f"plots={by_seq_dir}")


if __name__ == "__main__":
    main()
