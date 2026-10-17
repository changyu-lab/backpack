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

SEQ_DIMS = {
    "DrivingInCity": (960, 480),
    "AerialCity": (960, 480),
    "BranCastle2": (768, 384),
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def latitude_discard_ratio_for_sequence(seq, max_stretch, ctu_size=128):
    width, height = SEQ_DIMS.get(seq, (0, 0))
    if width <= 0 or height <= 0:
        return 0.0, 0, 0

    width_in_ctus = int(math.ceil(float(width) / float(ctu_size)))
    height_in_ctus = int(math.ceil(float(height) / float(ctu_size)))
    full_ctus = width_in_ctus * height_in_ctus
    retained = 0
    for cy in range(height_in_ctus):
        y = cy * ctu_size
        h = min(ctu_size, height - y)
        row_center = float(y) + 0.5 * float(h)
        phi = (0.5 - row_center / float(height)) * math.pi
        cos_phi = max(math.cos(abs(phi)), 1e-6)
        if 1.0 / cos_phi <= max_stretch:
            retained += width_in_ctus

    ratio = 1.0 - float(retained) / float(full_ctus) if full_ctus > 0 else 0.0
    return ratio, retained, full_ctus


def weighted_latitude_discard_ratio(sequences, max_stretch):
    retained_sum = 0
    full_sum = 0
    for seq in sequences:
        _, retained, full = latitude_discard_ratio_for_sequence(seq, max_stretch)
        retained_sum += retained
        full_sum += full
    return 1.0 - float(retained_sum) / float(full_sum) if full_sum > 0 else 0.0


def clean_data(df: pd.DataFrame, max_stretch: float):
    total = len(df)
    df = df.copy()
    numeric_cols = [
        "qp", "poc", "ctu", "ctu_x", "ctu_y", "x", "y", "w", "h",
        "latitude_deg", "cos_phi", "stretch", "qs", "ieff_raw", "satd",
        "residual_energy", "actual_bits", "ordinary_mse", "latitude_weighted_mse",
        "intra_ratio", "inter_ratio", "skip_ratio", "nonzero_coeff_ratio",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    keep = (
        (df["stretch"] <= max_stretch)
        & (df["qs"] > 0)
        & (df["actual_bits"] > 0)
        & (df["ordinary_mse"] > 0)
        & (df["latitude_weighted_mse"] > 0)
        & np.isfinite(df[numeric_cols]).all(axis=1)
    )
    return df.loc[keep].reset_index(drop=True), 0.0 if total == 0 else 1.0 - float(keep.sum()) / float(total)


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
    qs = np.asarray(df["qs"], dtype=float)
    x, scale = feature_values(df, feature)
    eps = 1e-12

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
    params = {
        "a": a,
        "b": b,
        "c": c if c is not None else np.nan,
        "d": d if d is not None else np.nan,
        "feature_scale": scale,
        "success": bool(res.success),
    }
    return pred, params


def plot_actual_vs_pred(y, pred_map, out_file, title, ylabel):
    plt.figure(figsize=(8, 6))
    for name, pred in pred_map.items():
        plt.scatter(y, pred, s=8, alpha=0.35, label=name)
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
    qps = sorted(df["qp"].unique())
    actual = [df.loc[df["qp"] == qp, target_col].mean() for qp in qps]
    plt.figure(figsize=(7, 5))
    plt.plot(qps, actual, "ko-", label="actual")
    for name, pred in pred_map.items():
        vals = [np.asarray(pred)[df["qp"].values == qp].mean() for qp in qps]
        plt.plot(qps, vals, marker="o", label=name)
    plt.xlabel("QP")
    plt.ylabel(target_col)
    plt.title(title)
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(out_file, dpi=160)
    plt.close()


def fit_rate_scope(df, discarded_ratio, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    preds = {}
    y = np.asarray(df["actual_bits"], dtype=float)
    for model, feature in RATE_MODELS:
        pred, params = fit_power_feature(df, "actual_bits", feature, exponent_sign=-1)
        r2, mape, log_rmse = metrics(y, pred)
        preds[model] = pred
        rows.append({
            "model": model,
            "R2": r2,
            "MAPE": mape,
            "log_RMSE": log_rmse,
            "sample_count": len(df),
            "discarded_ratio": discarded_ratio,
            **params,
        })
    table = pd.DataFrame(rows)
    table.to_csv(out_dir / "table_4_7_rate.csv", index=False)
    plot_actual_vs_pred(y, preds, out_dir / "figure_4_7_actual_vs_pred_bits.png",
                        "C1 actual bits vs predicted bits", "Predicted bits")
    plot_error_box(y, preds, out_dir / "figure_4_7_error_boxplot.png", "C1 error by model")
    plot_qp_curves(df, preds, "actual_bits", out_dir / "figure_4_7_qp_curves.png", "C1 QP trend")
    return table


def fit_dist_scope(df, discarded_ratio, out_dir):
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
            "discarded_ratio": discarded_ratio,
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
    table.to_csv(out_dir / "table_4_8_distortion.csv", index=False)
    plot_actual_vs_pred(y_mse, mse_preds, out_dir / "figure_4_8_actual_vs_pred_mse.png",
                        "C2 ordinary MSE actual vs predicted", "Predicted MSE")
    plot_actual_vs_pred(y_wmse, wmse_preds, out_dir / "figure_4_8_actual_vs_pred_weighted_mse.png",
                        "C2 weighted MSE actual vs predicted", "Predicted weighted MSE")
    plot_error_box(y_wmse, wmse_preds, out_dir / "figure_4_8_weighted_error_boxplot.png", "C2 weighted error by model")
    plot_qp_curves(df, wmse_preds, "latitude_weighted_mse", out_dir / "figure_4_8_qp_curves.png", "C2 weighted QP trend")
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
            "discarded_ratio": row["discarded_ratio"],
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
            "discarded_ratio": row["discarded_ratio"],
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
            x, scale = feature_values(train, feature)
            del x
            a = params["a"]
            b = params["b"]
            if feature is None:
                pred = a * np.power(np.asarray(test["qs"], dtype=float), b)
            else:
                xf = np.asarray(test[feature], dtype=float) / scale
                pred = a * np.power(np.asarray(test["qs"], dtype=float), b) * (params["c"] + params["d"] * xf)
            r2, mape, log_rmse = metrics(y_test, pred)
            rows.append({"held_out": held_out, "model": model, "R2": r2, "MAPE": mape, "log_RMSE": log_rmse, "sample_count": len(test)})
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description="Fit RC360 C1/C2 CTU models.")
    parser.add_argument("--max-stretch", type=float, default=1.2)
    parser.add_argument("--input", type=str, default="")
    args = parser.parse_args()

    root = repo_root()
    exp_root = root / "experiments" / "rc360_ctu_model"
    input_csv = Path(args.input) if args.input else exp_root / "data" / "all_ctu_samples.csv"
    df_raw = pd.read_csv(input_csv)
    df, discarded_ratio = clean_data(df_raw, args.max_stretch)
    if df.empty:
        raise RuntimeError("No usable CTU samples after filtering.")

    results = exp_root / "results"
    rate_summary = []
    dist_summary = []

    for seq in sorted(df["sequence"].unique()):
        seq_df = df[df["sequence"] == seq].reset_index(drop=True)
        seq_discarded, _, _ = latitude_discard_ratio_for_sequence(seq, args.max_stretch)
        out_dir = results / "by_sequence" / seq
        rate_table = fit_rate_scope(seq_df, seq_discarded, out_dir)
        dist_table = fit_dist_scope(seq_df, seq_discarded, out_dir)
        add_summary("by_sequence", seq, rate_table, dist_table, rate_summary, dist_summary)

    combined_dir = results / "combined_3seq"
    combined_discarded = weighted_latitude_discard_ratio(sorted(df["sequence"].unique()), args.max_stretch)
    rate_table = fit_rate_scope(df, combined_discarded, combined_dir)
    dist_table = fit_dist_scope(df, combined_discarded, combined_dir)
    add_summary("combined", "combined_3seq", rate_table, dist_table, rate_summary, dist_summary)

    pd.DataFrame(rate_summary).to_csv(results / "summary_rate_all_fits.csv", index=False)
    pd.DataFrame(dist_summary).to_csv(results / "summary_distortion_all_fits.csv", index=False)

    cross_dir = results / "cross_validation"
    cross_dir.mkdir(parents=True, exist_ok=True)
    cross_eval(df, "sequence", RATE_MODELS, "actual_bits", -1).to_csv(cross_dir / "cross_sequence_rate.csv", index=False)
    cross_eval(df, "qp", RATE_MODELS, "actual_bits", -1).to_csv(cross_dir / "cross_qp_rate.csv", index=False)
    cross_eval(df, "sequence", DIST_MODELS, "latitude_weighted_mse", 1).to_csv(cross_dir / "cross_sequence_distortion.csv", index=False)
    cross_eval(df, "qp", DIST_MODELS, "latitude_weighted_mse", 1).to_csv(cross_dir / "cross_qp_distortion.csv", index=False)
    print("Fitting complete:", results)


if __name__ == "__main__":
    main()
