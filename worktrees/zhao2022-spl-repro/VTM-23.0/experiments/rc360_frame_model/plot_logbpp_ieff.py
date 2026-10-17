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


def main():
    parser = argparse.ArgumentParser(description="Plot per-sequence ln(BPP) vs frame Ieff scatter.")
    parser.add_argument("--input", default="experiments/rc360_frame_model/data/qp17_50_5f/frame_samples.csv")
    parser.add_argument("--output-dir", default="experiments/rc360_frame_model/results_qp17_50_5f/logbpp_ieff")
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
    df["ieff_raw"] = pd.to_numeric(df["ieff_raw"], errors="coerce")
    df["command_qp"] = pd.to_numeric(df["command_qp"], errors="coerce")
    df["poc"] = pd.to_numeric(df["poc"], errors="coerce")

    numeric = ["poc", "command_qp", "bpp", "log_bpp", "ieff_raw"]
    df = df[np.isfinite(df[numeric]).all(axis=1) & (df["bpp"] > 0) & (df["ieff_raw"] > 0)].copy()
    if not args.include_i:
        df = df[(df["poc"] % 8) != 0].copy()

    rows = []
    for sequence, g in df.groupby("sequence"):
        x = g["ieff_raw"].to_numpy(dtype=float)
        y = g["log_bpp"].to_numpy(dtype=float)
        pearson = float(pd.Series(x).corr(pd.Series(y), method="pearson"))
        spearman = float(pd.Series(x).corr(pd.Series(y), method="spearman"))
        slope, intercept = np.polyfit(x, y, 1)
        pred = intercept + slope * x
        ss_res = float(np.sum((y - pred) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        r2_linear = 1.0 - ss_res / ss_tot if ss_tot > 0.0 else np.nan
        rows.append({
            "sequence": sequence,
            "sample_count": len(g),
            "ieff_min": float(np.min(x)),
            "ieff_mean": float(np.mean(x)),
            "ieff_max": float(np.max(x)),
            "log_bpp_min": float(np.min(y)),
            "log_bpp_mean": float(np.mean(y)),
            "log_bpp_max": float(np.max(y)),
            "pearson_logbpp_ieff": pearson,
            "spearman_logbpp_ieff": spearman,
            "linear_intercept": intercept,
            "linear_slope": slope,
            "linear_R2": r2_linear,
        })

        fit_x = np.linspace(float(np.min(x)), float(np.max(x)), 200)
        fit_y = intercept + slope * fit_x
        plt.figure(figsize=(8, 5))
        sc = plt.scatter(g["ieff_raw"], g["log_bpp"], c=g["command_qp"], cmap="viridis",
                         s=26, alpha=0.68)
        plt.plot(fit_x, fit_y, color="tab:red", linewidth=1.8, label=f"linear fit, R2={r2_linear:.3f}")
        plt.xlabel("Frame Ieff (mean of CTU Ieff)")
        plt.ylabel("ln(BPP)")
        plt.title(f"{sequence}: ln(BPP) vs Ieff")
        plt.grid(True, alpha=0.25)
        plt.legend()
        cbar = plt.colorbar(sc)
        cbar.set_label("Command QP")
        plt.tight_layout()
        plt.savefig(by_seq_dir / f"{sequence}_logbpp_vs_ieff.png", dpi=170)
        plt.close()

    pd.DataFrame(rows).to_csv(out_dir / "logbpp_ieff_stats.csv", index=False)

    plt.figure(figsize=(9, 6))
    for sequence, g in df.groupby("sequence"):
        plt.scatter(g["ieff_raw"], g["log_bpp"], s=18, alpha=0.5, label=sequence)
    plt.xlabel("Frame Ieff (mean of CTU Ieff)")
    plt.ylabel("ln(BPP)")
    plt.title("All sequences: ln(BPP) vs Ieff")
    plt.grid(True, alpha=0.25)
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(out_dir / "all_sequences_logbpp_vs_ieff.png", dpi=170)
    plt.close()

    print(f"samples={len(df)}")
    print(f"stats={out_dir / 'logbpp_ieff_stats.csv'}")
    print(f"plots={by_seq_dir}")


if __name__ == "__main__":
    main()
