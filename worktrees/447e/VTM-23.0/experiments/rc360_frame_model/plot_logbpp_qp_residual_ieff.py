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


def linear_metrics(x, y):
    slope, intercept = np.polyfit(x, y, 1)
    pred = intercept + slope * x
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0.0 else np.nan
    rmse = float(np.sqrt(np.mean((y - pred) ** 2)))
    return intercept, slope, pred, r2, rmse


def main():
    parser = argparse.ArgumentParser(description="Plot QP-removed ln(BPP) residual vs frame Ieff.")
    parser.add_argument("--input", default="experiments/rc360_frame_model/data/qp17_50_5f/frame_samples.csv")
    parser.add_argument("--output-dir", default="experiments/rc360_frame_model/results_qp17_50_5f/logbpp_qp_residual_ieff")
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

    all_rows = []
    residual_frames = []

    for sequence, g0 in df.groupby("sequence"):
        g = g0.copy()
        qp = g["command_qp"].to_numpy(dtype=float)
        log_bpp = g["log_bpp"].to_numpy(dtype=float)
        qp_intercept, qp_slope, qp_pred, qp_r2, qp_rmse = linear_metrics(qp, log_bpp)
        g["fitted_log_bpp_from_qp"] = qp_pred
        g["log_bpp_qp_residual"] = log_bpp - qp_pred

        ieff = g["ieff_raw"].to_numpy(dtype=float)
        resid = g["log_bpp_qp_residual"].to_numpy(dtype=float)
        res_intercept, res_slope, res_pred, res_r2, res_rmse = linear_metrics(ieff, resid)
        pearson = float(pd.Series(ieff).corr(pd.Series(resid), method="pearson"))
        spearman = float(pd.Series(ieff).corr(pd.Series(resid), method="spearman"))

        all_rows.append({
            "sequence": sequence,
            "sample_count": len(g),
            "qp_intercept": qp_intercept,
            "qp_slope": qp_slope,
            "qp_R2_logBPP": qp_r2,
            "qp_RMSE_logBPP": qp_rmse,
            "residual_vs_ieff_intercept": res_intercept,
            "residual_vs_ieff_slope": res_slope,
            "residual_vs_ieff_R2": res_r2,
            "residual_vs_ieff_RMSE": res_rmse,
            "pearson_residual_ieff": pearson,
            "spearman_residual_ieff": spearman,
        })
        residual_frames.append(g)

        fit_x = np.linspace(float(np.min(ieff)), float(np.max(ieff)), 200)
        fit_y = res_intercept + res_slope * fit_x

        plt.figure(figsize=(8, 5))
        sc = plt.scatter(g["ieff_raw"], g["log_bpp_qp_residual"], c=g["command_qp"],
                         cmap="viridis", s=26, alpha=0.68)
        plt.axhline(0.0, color="black", linewidth=1.0)
        plt.plot(fit_x, fit_y, color="tab:red", linewidth=1.8,
                 label=f"residual fit, R2={res_r2:.3f}")
        plt.xlabel("Frame Ieff (mean of CTU Ieff)")
        plt.ylabel("ln(BPP) - fitted ln(BPP | QP)")
        plt.title(f"{sequence}: QP-removed ln(BPP) residual vs Ieff")
        plt.grid(True, alpha=0.25)
        plt.legend()
        cbar = plt.colorbar(sc)
        cbar.set_label("Command QP")
        plt.tight_layout()
        plt.savefig(by_seq_dir / f"{sequence}_logbpp_qp_residual_vs_ieff.png", dpi=170)
        plt.close()

    summary = pd.DataFrame(all_rows)
    summary.to_csv(out_dir / "logbpp_qp_residual_ieff_stats.csv", index=False)
    residual_df = pd.concat(residual_frames, ignore_index=True)
    residual_df.to_csv(out_dir / "frame_logbpp_qp_residual_samples.csv", index=False)

    plt.figure(figsize=(9, 6))
    for sequence, g in residual_df.groupby("sequence"):
        plt.scatter(g["ieff_raw"], g["log_bpp_qp_residual"], s=18, alpha=0.5, label=sequence)
    plt.axhline(0.0, color="black", linewidth=1.0)
    plt.xlabel("Frame Ieff (mean of CTU Ieff)")
    plt.ylabel("ln(BPP) - fitted ln(BPP | QP)")
    plt.title("All sequences: QP-removed ln(BPP) residual vs Ieff")
    plt.grid(True, alpha=0.25)
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(out_dir / "all_sequences_logbpp_qp_residual_vs_ieff.png", dpi=170)
    plt.close()

    print(f"samples={len(residual_df)}")
    print(f"stats={out_dir / 'logbpp_qp_residual_ieff_stats.csv'}")
    print(f"samples_csv={out_dir / 'frame_logbpp_qp_residual_samples.csv'}")
    print(f"plots={by_seq_dir}")


if __name__ == "__main__":
    main()
