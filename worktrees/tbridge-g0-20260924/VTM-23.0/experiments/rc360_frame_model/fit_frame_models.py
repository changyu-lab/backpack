#!/usr/bin/env python3
import argparse
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import least_squares


RATE_MODELS = [
    ("R(QS)", None),
    ("R(QS,SATD)", "satd"),
    ("R(QS,Eres)", "residual_energy"),
    ("R(QS,rho)", "nonzero_coeff_ratio"),
    ("R(QS,Ieff)", "ieff_raw"),
]

DIST_MODELS = [
    ("D(QS)", None),
    ("D(QS,SATD)", "satd"),
    ("D(QS,Eres)", "residual_energy"),
    ("D(QS,Ieff)", "ieff_raw"),
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def clean_data(df):
    df = df.copy()
    df["actual_bpp"] = pd.to_numeric(df["actual_bits"], errors="coerce") / (
        pd.to_numeric(df["width"], errors="coerce") * pd.to_numeric(df["height"], errors="coerce")
    )
    numeric_cols = [
        "command_qp", "poc", "frame_qp", "qp", "qs", "command_qs", "ctu_count",
        "width", "height", "frame_area", "ieff_raw", "satd", "residual_energy",
        "actual_bits", "actual_bpp", "ordinary_mse", "latitude_weighted_mse", "intra_ratio",
        "inter_ratio", "skip_ratio", "nonzero_coeff_ratio",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    keep = (
        (df["qs"] > 0)
        & ((df["poc"] % 8) != 0)
        & (df["actual_bits"] > 0)
        & (df["actual_bpp"] > 0)
        & (df["ordinary_mse"] > 0)
        & (df["latitude_weighted_mse"] > 0)
        & np.isfinite(df[numeric_cols]).all(axis=1)
    )
    return df.loc[keep].reset_index(drop=True)


def metrics(y, pred):
    eps = 1e-12
    y = np.asarray(y, dtype=float)
    pred = np.maximum(np.asarray(pred, dtype=float), eps)
    ss_res = np.sum((y - pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    mape = np.mean(np.abs((y - pred) / np.maximum(y, eps))) * 100.0
    log_rmse = math.sqrt(np.mean((np.log(np.maximum(y, eps)) - np.log(pred)) ** 2))
    return r2, mape, log_rmse


def feature_values(df, feature):
    if feature is None:
        return None, 1.0
    x = np.asarray(df[feature], dtype=float)
    positive = x[x > 0]
    scale = float(np.mean(positive)) if positive.size else 1.0
    if scale <= 0 or not np.isfinite(scale):
        scale = 1.0
    return x / scale, scale


def fit_power_feature(df, target_col, feature, exponent_sign):
    y = np.asarray(df[target_col], dtype=float)
    eps = 1e-12
    x, scale = feature_values(df, feature)

    def safe_exp(v):
        return math.exp(float(np.clip(v, -50.0, 50.0)))

    def unpack(p):
        a = safe_exp(p[0])
        b_mag = safe_exp(p[1])
        b = -b_mag if exponent_sign < 0 else b_mag
        if x is None:
            return a, b, None, None
        c = safe_exp(p[2])
        d = safe_exp(p[3])
        return a, b, c, d

    def predict_from_params(p, frame):
        a, b, c, d = unpack(p)
        q = np.asarray(frame["qs"], dtype=float)
        if feature is None:
            return np.maximum(a * np.power(q, b), eps)
        xf = np.asarray(frame[feature], dtype=float) / scale
        return np.maximum(a * np.power(q, b) * (c + d * xf), eps)

    ylog = np.log(np.maximum(y, eps))
    if feature is None:
        x0 = np.array([np.log(np.median(y)), np.log(1.0)])
    else:
        x0 = np.array([np.log(np.median(y)), np.log(1.0), np.log(1.0), np.log(0.1)])

    def residual(p):
        return np.log(predict_from_params(p, df)) - ylog

    lower = np.full_like(x0, -50.0, dtype=float)
    upper = np.full_like(x0, 50.0, dtype=float)
    res = least_squares(residual, x0, bounds=(lower, upper), max_nfev=20000)
    pred = predict_from_params(res.x, df)
    a, b, c, d = unpack(res.x)
    return pred, {
        "a": a,
        "b": b,
        "c": c if c is not None else np.nan,
        "d": d if d is not None else np.nan,
        "feature_scale": scale,
        "success": bool(res.success),
    }


def plot_actual_vs_pred(y, pred_map, out_file, title, ylabel):
    plt.figure(figsize=(8, 6))
    for name, pred in pred_map.items():
        plt.scatter(y, pred, s=12, alpha=0.45, label=name)
    lo = min(float(np.min(y)), *(float(np.min(v)) for v in pred_map.values()))
    hi = max(float(np.max(y)), *(float(np.max(v)) for v in pred_map.values()))
    plt.plot([lo, hi], [lo, hi], "k--", linewidth=1)
    plt.xlabel("Actual")
    plt.ylabel(ylabel)
    plt.title(title)
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(out_file, dpi=160)
    plt.close()


def plot_error_box(y, pred_map, out_file, title):
    errors = []
    labels = []
    for name, pred in pred_map.items():
        errors.append(100.0 * (np.asarray(pred) - y) / np.maximum(y, 1e-12))
        labels.append(name)
    plt.figure(figsize=(9, 5))
    plt.boxplot(errors, labels=labels, showfliers=False)
    plt.axhline(0.0, color="k", linewidth=1)
    plt.ylabel("Prediction error (%)")
    plt.title(title)
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    plt.savefig(out_file, dpi=160)
    plt.close()


def plot_qp_curves(df, pred_map, target_col, out_file, title):
    qps = sorted(df["command_qp"].unique())
    actual = [df.loc[df["command_qp"] == qp, target_col].mean() for qp in qps]
    plt.figure(figsize=(7, 5))
    plt.plot(qps, actual, "ko-", label="actual")
    for name, pred in pred_map.items():
        vals = [np.asarray(pred)[df["command_qp"].values == qp].mean() for qp in qps]
        plt.plot(qps, vals, marker="o", label=name)
    plt.xlabel("Command QP")
    plt.ylabel(target_col)
    plt.title(title)
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(out_file, dpi=160)
    plt.close()


def fit_rate_scope(df, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    preds = {}
    y = np.asarray(df["actual_bpp"], dtype=float)
    for model, feature in RATE_MODELS:
        pred, params = fit_power_feature(df, "actual_bpp", feature, exponent_sign=-1)
        r2, mape, log_rmse = metrics(y, pred)
        preds[model] = pred
        rows.append({"model": model, "R2": r2, "MAPE": mape, "log_RMSE": log_rmse,
                     "sample_count": len(df), **params})
    table = pd.DataFrame(rows)
    table.to_csv(out_dir / "table_frame_rate.csv", index=False)
    plot_actual_vs_pred(y, preds, out_dir / "frame_actual_vs_pred_bpp.png",
                        "Frame rate model: actual bpp vs predicted bpp", "Predicted bpp")
    plot_error_box(y, preds, out_dir / "frame_rate_error_boxplot.png", "Frame rate error by model")
    plot_qp_curves(df, preds, "actual_bpp", out_dir / "frame_rate_qp_curves.png", "Frame rate QP trend")
    return table


def fit_dist_scope(df, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    mse_preds = {}
    wmse_preds = {}
    y_mse = np.asarray(df["ordinary_mse"], dtype=float)
    y_wmse = np.asarray(df["latitude_weighted_mse"], dtype=float)
    for model, feature in DIST_MODELS:
        pred_mse, params_mse = fit_power_feature(df, "ordinary_mse", feature, exponent_sign=1)
        pred_wmse, params_wmse = fit_power_feature(df, "latitude_weighted_mse", feature, exponent_sign=1)
        r2_mse, mape_mse, log_rmse_mse = metrics(y_mse, pred_mse)
        r2_wmse, mape_wmse, log_rmse_wmse = metrics(y_wmse, pred_wmse)
        mse_preds[model] = pred_mse
        wmse_preds[model] = pred_wmse
        rows.append({
            "model": model,
            "MSE_R2": r2_mse,
            "Weighted_MSE_R2": r2_wmse,
            "MAPE": mape_mse,
            "Weighted_MAPE": mape_wmse,
            "log_RMSE": log_rmse_mse,
            "Weighted_log_RMSE": log_rmse_wmse,
            "sample_count": len(df),
            "ordinary_a": params_mse["a"],
            "ordinary_b": params_mse["b"],
            "ordinary_c": params_mse["c"],
            "ordinary_d": params_mse["d"],
            "weighted_a": params_wmse["a"],
            "weighted_b": params_wmse["b"],
            "weighted_c": params_wmse["c"],
            "weighted_d": params_wmse["d"],
        })
    table = pd.DataFrame(rows)
    table.to_csv(out_dir / "table_frame_distortion.csv", index=False)
    plot_actual_vs_pred(y_mse, mse_preds, out_dir / "frame_actual_vs_pred_mse.png",
                        "Frame distortion model: ordinary MSE", "Predicted MSE")
    plot_actual_vs_pred(y_wmse, wmse_preds, out_dir / "frame_actual_vs_pred_weighted_mse.png",
                        "Frame distortion model: weighted MSE", "Predicted weighted MSE")
    plot_error_box(y_wmse, wmse_preds, out_dir / "frame_distortion_weighted_error_boxplot.png",
                   "Frame weighted distortion error by model")
    plot_qp_curves(df, wmse_preds, "latitude_weighted_mse", out_dir / "frame_distortion_qp_curves.png",
                   "Frame weighted distortion QP trend")
    return table


def add_summary(scope, name, rate_table, dist_table, rate_summary, dist_summary):
    for _, row in rate_table.iterrows():
        rate_summary.append({
            "fit_scope": scope,
            "sequence_or_combined": name,
            "model": row["model"],
            "R2": row["R2"],
            "MAPE": row["MAPE"],
            "log_RMSE": row["log_RMSE"],
            "sample_count": row["sample_count"],
        })
    for _, row in dist_table.iterrows():
        dist_summary.append({
            "fit_scope": scope,
            "sequence_or_combined": name,
            "model": row["model"],
            "R2": row["Weighted_MSE_R2"],
            "MAPE": row["Weighted_MAPE"],
            "log_RMSE": row["Weighted_log_RMSE"],
            "sample_count": row["sample_count"],
        })


def cross_eval(df, group_col, models, target_col, exponent_sign):
    rows = []
    for held_out in sorted(df[group_col].unique()):
        train = df[df[group_col] != held_out].reset_index(drop=True)
        test = df[df[group_col] == held_out].reset_index(drop=True)
        if len(train) == 0 or len(test) == 0:
            continue
        y_test = np.asarray(test[target_col], dtype=float)
        for model, feature in models:
            _, params = fit_power_feature(train, target_col, feature, exponent_sign)
            _, scale = feature_values(train, feature)
            a = params["a"]
            b = params["b"]
            if feature is None:
                pred = a * np.power(np.asarray(test["qs"], dtype=float), b)
            else:
                xf = np.asarray(test[feature], dtype=float) / scale
                pred = a * np.power(np.asarray(test["qs"], dtype=float), b) * (params["c"] + params["d"] * xf)
            r2, mape, log_rmse = metrics(y_test, pred)
            rows.append({"held_out": held_out, "model": model, "R2": r2, "MAPE": mape,
                         "log_RMSE": log_rmse, "sample_count": len(test)})
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description="Fit RC360 frame-level C1/C2 models.")
    parser.add_argument("--input", type=str, default="")
    parser.add_argument("--results-dir", type=str, default="")
    args = parser.parse_args()

    root = repo_root()
    exp_root = root / "experiments" / "rc360_frame_model"
    input_csv = Path(args.input) if args.input else exp_root / "data" / "frame_samples.csv"
    df = clean_data(pd.read_csv(input_csv))
    if df.empty:
        raise RuntimeError("No usable frame samples.")

    results = Path(args.results_dir) if args.results_dir else exp_root / "results"
    rate_summary = []
    dist_summary = []

    for seq in sorted(df["sequence"].unique()):
        seq_df = df[df["sequence"] == seq].reset_index(drop=True)
        out_dir = results / "by_sequence" / seq
        rate_table = fit_rate_scope(seq_df, out_dir)
        dist_table = fit_dist_scope(seq_df, out_dir)
        add_summary("by_sequence", seq, rate_table, dist_table, rate_summary, dist_summary)

    combined_dir = results / "combined_5seq"
    rate_table = fit_rate_scope(df, combined_dir)
    dist_table = fit_dist_scope(df, combined_dir)
    add_summary("combined", "combined_5seq", rate_table, dist_table, rate_summary, dist_summary)

    pd.DataFrame(rate_summary).to_csv(results / "summary_frame_rate_all_fits.csv", index=False)
    pd.DataFrame(dist_summary).to_csv(results / "summary_frame_distortion_all_fits.csv", index=False)

    cross_dir = results / "cross_validation"
    cross_dir.mkdir(parents=True, exist_ok=True)
    cross_eval(df, "sequence", RATE_MODELS, "actual_bpp", -1).to_csv(cross_dir / "cross_sequence_frame_rate.csv", index=False)
    cross_eval(df, "command_qp", RATE_MODELS, "actual_bpp", -1).to_csv(cross_dir / "cross_qp_frame_rate.csv", index=False)
    cross_eval(df, "sequence", DIST_MODELS, "latitude_weighted_mse", 1).to_csv(cross_dir / "cross_sequence_frame_distortion.csv", index=False)
    cross_eval(df, "command_qp", DIST_MODELS, "latitude_weighted_mse", 1).to_csv(cross_dir / "cross_qp_frame_distortion.csv", index=False)
    print("Frame-level fitting complete:", results)


if __name__ == "__main__":
    main()
