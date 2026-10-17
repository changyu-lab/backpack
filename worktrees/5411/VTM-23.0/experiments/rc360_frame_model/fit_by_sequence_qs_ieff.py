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


def metrics(y, pred):
    eps = 1e-12
    y = np.asarray(y, dtype=float)
    pred = np.maximum(np.asarray(pred, dtype=float), eps)
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    mape = float(np.mean(np.abs((y - pred) / np.maximum(y, eps))) * 100.0)
    log_rmse = float(np.sqrt(np.mean((np.log(np.maximum(y, eps)) - np.log(pred)) ** 2)))
    return r2, mape, log_rmse


def design_matrix(model, ln_qs, ln_ieff_norm):
    cols = [np.ones_like(ln_qs)]
    names = ["intercept"]
    if model == "QS":
        cols += [ln_qs]
        names += ["lnQS"]
    elif model == "QS+Ieff":
        cols += [ln_qs, ln_ieff_norm]
        names += ["lnQS", "lnIeffNorm"]
    elif model == "QS+Ieff+Interaction":
        cols += [ln_qs, ln_ieff_norm, ln_qs * ln_ieff_norm]
        names += ["lnQS", "lnIeffNorm", "lnQS_x_lnIeffNorm"]
    elif model == "QS+Ieff+Quad":
        cols += [
            ln_qs,
            ln_ieff_norm,
            ln_qs * ln_ieff_norm,
            ln_ieff_norm * ln_ieff_norm,
            ln_qs * ln_qs,
        ]
        names += ["lnQS", "lnIeffNorm", "lnQS_x_lnIeffNorm", "lnIeffNorm2", "lnQS2"]
    else:
        raise ValueError(model)
    return np.column_stack(cols), names


def fit_ols(model, df):
    eps = 1e-12
    y = np.asarray(df["bpp"], dtype=float)
    log_y = np.log(np.maximum(y, eps))
    ieff_scale = float(np.median(df["ieff_raw"]))
    if not np.isfinite(ieff_scale) or ieff_scale <= 0:
        ieff_scale = 1.0
    ln_qs = np.log(np.maximum(np.asarray(df["qs"], dtype=float), eps))
    ln_ieff_norm = np.log(np.maximum(np.asarray(df["ieff_raw"], dtype=float) / ieff_scale, eps))
    x, names = design_matrix(model, ln_qs, ln_ieff_norm)
    coef, *_ = np.linalg.lstsq(x, log_y, rcond=None)
    log_pred = x @ coef
    pred = np.exp(log_pred)
    r2, mape, log_rmse = metrics(y, pred)
    out = {
        "model": model,
        "target": "BPP",
        "log_model": "ln(BPP)=OLS(features)",
        "sample_count": len(df),
        "R2": r2,
        "MAPE": mape,
        "log_RMSE": log_rmse,
        "ieff_scale_median": ieff_scale,
        "formula_features": ";".join(names),
    }
    for name, value in zip(names, coef):
        out[f"coef_{name}"] = float(value)
    return out, pred


def clean_data(df, use_command_qs=False):
    df = df.copy()
    df["bpp"] = pd.to_numeric(df["actual_bits"], errors="coerce") / (
        pd.to_numeric(df["width"], errors="coerce") * pd.to_numeric(df["height"], errors="coerce")
    )
    if use_command_qs:
        df["qs"] = pd.to_numeric(df["command_qs"], errors="coerce")
    else:
        df["qs"] = pd.to_numeric(df["qs"], errors="coerce")
    numeric = ["poc", "command_qp", "bpp", "qs", "ieff_raw"]
    for col in numeric:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    keep = (
        ((df["poc"] % 8) != 0)
        & (df["bpp"] > 0)
        & (df["qs"] > 0)
        & (df["ieff_raw"] > 0)
        & np.isfinite(df[numeric]).all(axis=1)
    )
    return df.loc[keep].reset_index(drop=True)


def plot_sequence(df, pred_map, out_dir, sequence):
    y = np.asarray(df["bpp"], dtype=float)
    plt.figure(figsize=(8, 6))
    for model, pred in pred_map.items():
        plt.scatter(y, pred, s=20, alpha=0.45, label=model)
    lo = min(float(np.min(y)), *(float(np.min(p)) for p in pred_map.values()))
    hi = max(float(np.max(y)), *(float(np.max(p)) for p in pred_map.values()))
    plt.plot([lo, hi], [lo, hi], "k--", linewidth=1)
    plt.xlabel("Actual BPP")
    plt.ylabel("Predicted BPP")
    plt.title(f"{sequence}: per-sequence QS/Ieff model")
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(out_dir / f"{sequence}_actual_vs_pred_bpp.png", dpi=170)
    plt.close()

    plt.figure(figsize=(8, 5))
    for model, pred in pred_map.items():
        err = np.log(np.maximum(pred, 1e-12)) - np.log(np.maximum(y, 1e-12))
        plt.scatter(df["command_qp"], err, s=20, alpha=0.5, label=model)
    plt.axhline(0.0, color="black", linewidth=1)
    plt.xlabel("Command QP")
    plt.ylabel("log prediction error")
    plt.title(f"{sequence}: log error vs QP")
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(out_dir / f"{sequence}_log_error_vs_qp.png", dpi=170)
    plt.close()


def main():
    parser = argparse.ArgumentParser(description="Fit per-sequence frame BPP models using QS and Ieff only.")
    parser.add_argument("--input", default="experiments/rc360_frame_model/data/qp17_50_5f/frame_samples.csv")
    parser.add_argument("--output-dir", default="experiments/rc360_frame_model/results_qp17_50_5f/by_sequence_qs_ieff")
    parser.add_argument("--use-command-qs", action="store_true", help="Use command_qs instead of frame qs.")
    args = parser.parse_args()

    root = repo_root()
    input_csv = Path(args.input)
    if not input_csv.is_absolute():
        input_csv = root / input_csv
    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    df = clean_data(pd.read_csv(input_csv), use_command_qs=args.use_command_qs)
    models = ["QS", "QS+Ieff", "QS+Ieff+Interaction", "QS+Ieff+Quad"]
    rows = []
    best_rows = []
    for sequence, g in df.groupby("sequence"):
        seq_dir = out_dir / sequence
        seq_dir.mkdir(parents=True, exist_ok=True)
        pred_map = {}
        seq_rows = []
        for model in models:
            row, pred = fit_ols(model, g)
            row["sequence"] = sequence
            row["qs_source"] = "command_qs" if args.use_command_qs else "frame_qs"
            rows.append(row)
            seq_rows.append(row)
            pred_map[model] = pred
        seq_table = pd.DataFrame(seq_rows).sort_values("R2", ascending=False)
        seq_table.to_csv(seq_dir / "table_by_sequence_qs_ieff.csv", index=False)
        best_rows.append(seq_table.iloc[0].to_dict())
        plot_sequence(g, pred_map, seq_dir, sequence)

    summary = pd.DataFrame(rows)
    summary.to_csv(out_dir / "summary_by_sequence_qs_ieff_all_models.csv", index=False)
    pd.DataFrame(best_rows).to_csv(out_dir / "summary_by_sequence_qs_ieff_best.csv", index=False)
    print(f"samples={len(df)}")
    print(f"summary={out_dir / 'summary_by_sequence_qs_ieff_all_models.csv'}")
    print(f"best={out_dir / 'summary_by_sequence_qs_ieff_best.csv'}")


if __name__ == "__main__":
    main()
