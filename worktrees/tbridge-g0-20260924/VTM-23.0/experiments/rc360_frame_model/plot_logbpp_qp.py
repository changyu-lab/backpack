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
    parser = argparse.ArgumentParser(description="Plot per-sequence logBPP vs QP scatter.")
    parser.add_argument("--input", default="experiments/rc360_frame_model/data/qp17_50_5f/frame_samples.csv")
    parser.add_argument("--output-dir", default="experiments/rc360_frame_model/results_qp17_50_5f/logbpp_qp")
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
    df["log10_bpp"] = np.log10(df["bpp"])

    numeric = ["command_qp", "poc", "bpp", "log_bpp", "log10_bpp"]
    for col in numeric:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[np.isfinite(df[numeric]).all(axis=1) & (df["bpp"] > 0)].copy()
    if not args.include_i:
        df = df[(df["poc"] % 8) != 0].copy()

    stats = (
        df.groupby(["sequence", "command_qp"])
        .agg(
            frame_count=("poc", "count"),
            mean_bpp=("bpp", "mean"),
            std_bpp=("bpp", "std"),
            mean_log_bpp=("log_bpp", "mean"),
            std_log_bpp=("log_bpp", "std"),
            mean_log10_bpp=("log10_bpp", "mean"),
            std_log10_bpp=("log10_bpp", "std"),
        )
        .reset_index()
    )
    stats.to_csv(out_dir / "logbpp_qp_stats.csv", index=False)

    fit_rows = []

    for sequence, g in df.groupby("sequence"):
        s = stats[stats["sequence"] == sequence]
        x = g["command_qp"].to_numpy(dtype=float)
        y = g["log_bpp"].to_numpy(dtype=float)
        slope, intercept = np.polyfit(x, y, 1)
        pred = intercept + slope * x
        ss_res = float(np.sum((y - pred) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0.0 else np.nan
        rmse = float(np.sqrt(np.mean((y - pred) ** 2)))
        bpp = g["bpp"].to_numpy(dtype=float)
        pred_bpp = np.exp(pred)
        mape_bpp = float(np.mean(np.abs((bpp - pred_bpp) / np.maximum(bpp, 1e-12))) * 100.0)
        fit_rows.append({
            "scope": "by_sequence",
            "sequence": sequence,
            "intercept": intercept,
            "slope": slope,
            "model": "ln(BPP)=intercept+slope*command_qp",
            "R2_log": r2,
            "RMSE_log": rmse,
            "MAPE_BPP": mape_bpp,
            "sample_count": len(g),
        })

        fit_x = np.linspace(float(x.min()), float(x.max()), 200)
        fit_y = intercept + slope * fit_x

        plt.figure(figsize=(8, 5))
        plt.scatter(g["command_qp"], g["log_bpp"], s=24, alpha=0.55, label="P-frame samples")
        plt.plot(s["command_qp"], s["mean_log_bpp"], color="black", linewidth=1.6, marker="o", markersize=3,
                 label="mean per QP")
        plt.plot(fit_x, fit_y, color="tab:red", linewidth=2.0,
                 label=f"linear fit: y={intercept:.3f}{slope:+.3f}QP")
        plt.xlabel("Command QP")
        plt.ylabel("ln(BPP)")
        plt.title(f"{sequence}: ln(BPP) vs QP, R2={r2:.4f}")
        plt.grid(True, alpha=0.25)
        plt.legend()
        plt.tight_layout()
        plt.savefig(by_seq_dir / f"{sequence}_logbpp_vs_qp.png", dpi=170)
        plt.close()

    x_all = df["command_qp"].to_numpy(dtype=float)
    y_all = df["log_bpp"].to_numpy(dtype=float)
    slope_all, intercept_all = np.polyfit(x_all, y_all, 1)
    pred_all = intercept_all + slope_all * x_all
    ss_res_all = float(np.sum((y_all - pred_all) ** 2))
    ss_tot_all = float(np.sum((y_all - np.mean(y_all)) ** 2))
    r2_all = 1.0 - ss_res_all / ss_tot_all if ss_tot_all > 0.0 else np.nan
    rmse_all = float(np.sqrt(np.mean((y_all - pred_all) ** 2)))
    mape_bpp_all = float(
        np.mean(np.abs((df["bpp"].to_numpy(dtype=float) - np.exp(pred_all)) / np.maximum(df["bpp"].to_numpy(dtype=float), 1e-12))) * 100.0
    )
    fit_rows.append({
        "scope": "combined",
        "sequence": "combined_5seq",
        "intercept": intercept_all,
        "slope": slope_all,
        "model": "ln(BPP)=intercept+slope*command_qp",
        "R2_log": r2_all,
        "RMSE_log": rmse_all,
        "MAPE_BPP": mape_bpp_all,
        "sample_count": len(df),
    })
    pd.DataFrame(fit_rows).to_csv(out_dir / "logbpp_qp_linear_fit.csv", index=False)

    plt.figure(figsize=(9, 6))
    for sequence, g in df.groupby("sequence"):
        plt.scatter(g["command_qp"], g["log_bpp"], s=16, alpha=0.45, label=sequence)
    fit_x = np.linspace(float(x_all.min()), float(x_all.max()), 200)
    plt.plot(fit_x, intercept_all + slope_all * fit_x, color="black", linewidth=2.2,
             label=f"combined fit: y={intercept_all:.3f}{slope_all:+.3f}QP")
    plt.xlabel("Command QP")
    plt.ylabel("ln(BPP)")
    plt.title(f"All sequences: ln(BPP) vs QP, R2={r2_all:.4f}")
    plt.grid(True, alpha=0.25)
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(out_dir / "all_sequences_logbpp_vs_qp.png", dpi=170)
    plt.close()

    print(f"samples={len(df)}")
    print(f"stats={out_dir / 'logbpp_qp_stats.csv'}")
    print(f"fit={out_dir / 'logbpp_qp_linear_fit.csv'}")
    print(f"plots={by_seq_dir}")


if __name__ == "__main__":
    main()
