#!/usr/bin/env python3
"""Fit a cheap pre-gate for Skip18 real pruning.

The gate is not a pruning decision. It decides whether the encoder should pay
for the current-block response predictor. Positives are rows where the full
Skip18-v2 predictor would trigger the conservative actual-QP {0} pruning.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np


DEFAULT_FINAL_THRESHOLDS = {
    19: -5356679.494313986,
    24: -1792025.6619448862,
    29: -15963393.063854005,
    34: -9556709.148067622,
}


def open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", newline="", encoding="utf-8")
    return path.open("r", newline="", encoding="utf-8")


def parse_thresholds(spec: str | None) -> dict[int, float]:
    if not spec:
        return dict(DEFAULT_FINAL_THRESHOLDS)
    out: dict[int, float] = {}
    for item in spec.split(","):
        if not item:
            continue
        qp_s, thr_s = item.split(":", 1)
        out[int(qp_s)] = float(thr_s)
    if not out:
        raise ValueError("empty final threshold specification")
    return out


def nearest_qp(qp: int, buckets: Iterable[int]) -> int:
    return min(buckets, key=lambda b: (abs(qp - b), b))


def safe_float(row: dict[str, str], key: str, default: float = math.nan) -> float:
    value = row.get(key, "")
    if value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def quantile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return math.inf
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = max(0.0, min(1.0, p)) * (len(sorted_values) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_values[lo]
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def format_cpp_array(values: list[float]) -> str:
    return ", ".join(f"{v:.17g}" for v in values)


def pack_meta_key(qp: int, width: int, height: int, lat_bin: int, set_idx: int, transpose: int) -> int:
    key = qp
    for value, mult in ((width, 256), (height, 256), (lat_bin, 8), (set_idx, 8), (transpose, 2)):
        key = key * mult + value
    return key


FEATURE_NAMES = [
    "g1_cov",
    "g2_cov",
    "max_g_cov",
    "min_g_cov",
    "pred_rate_gain_bits1",
    "pred_rate_gain_bits2",
    "log_zero_q1",
    "log_zero_q2",
    "log_retained_q1",
    "log_retained_q2",
    "zero_ratio1",
    "zero_ratio2",
    "log_sigma_q",
    "log2_w",
    "log2_h",
    "lat_bin",
    "set_idx",
    "transpose",
    "out_n_is_8",
    "k_in_is_48",
]


def cheap_features(row: dict[str, str]) -> list[float]:
    g1 = safe_float(row, "G1_cov", 0.0)
    g2 = safe_float(row, "G2_cov", 0.0)
    r1 = safe_float(row, "predRateGainBits1", 0.0)
    r2 = safe_float(row, "predRateGainBits2", 0.0)
    sigma2 = max(0.0, safe_float(row, "sigma2", 0.0))
    q_step = max(1e-9, safe_float(row, "qStep", 1.0))
    inv_q2 = 1.0 / (q_step * q_step + 1e-12)
    z1 = max(0.0, safe_float(row, "tableZeroOutEnergy1", 0.0))
    z2 = max(0.0, safe_float(row, "tableZeroOutEnergy2", 0.0))
    ret1 = max(0.0, safe_float(row, "tableRetainedEnergy1", 0.0))
    ret2 = max(0.0, safe_float(row, "tableRetainedEnergy2", 0.0))
    w = max(1.0, safe_float(row, "W", 1.0))
    h = max(1.0, safe_float(row, "H", 1.0))
    out_n = safe_float(row, "outN", 16.0)
    k_in = safe_float(row, "kIn", 48.0)
    return [
        g1,
        g2,
        max(g1, g2),
        min(g1, g2),
        r1,
        r2,
        math.log1p(z1 * inv_q2),
        math.log1p(z2 * inv_q2),
        math.log1p(ret1 * inv_q2),
        math.log1p(ret2 * inv_q2),
        z1 / (z1 + ret1 + 1e-12),
        z2 / (z2 + ret2 + 1e-12),
        math.log1p(sigma2 * inv_q2),
        math.log2(w),
        math.log2(h),
        safe_float(row, "latBin", 0.0),
        safe_float(row, "setIdx", 0.0),
        safe_float(row, "transpose", 0.0),
        1.0 if int(round(out_n)) == 8 else 0.0,
        1.0 if int(round(k_in)) == 48 else 0.0,
    ]


def fit_weighted_ridge(x: np.ndarray, y: np.ndarray, ridge: float = 1e-4) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, np.ndarray]:
    if len(y) == 0:
        n = len(FEATURE_NAMES)
        return np.zeros(n), np.ones(n), np.zeros(n), 0.0, np.zeros(0)
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-9] = 1.0
    xs = (x - mean) / scale
    pos = max(1, int(np.sum(y > 0.5)))
    neg = max(1, int(len(y) - pos))
    weights = np.where(y > 0.5, len(y) / (2.0 * pos), len(y) / (2.0 * neg))
    design = np.concatenate([np.ones((len(y), 1)), xs], axis=1)
    sw = np.sqrt(weights)[:, None]
    a = design * sw
    b = y * sw[:, 0]
    reg = np.eye(design.shape[1]) * ridge
    reg[0, 0] = 0.0
    beta = np.linalg.solve(a.T @ a + reg, a.T @ b)
    scores = design @ beta
    return mean, scale, beta[1:], float(beta[0]), scores


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+", type=Path)
    ap.add_argument("--final-threshold", default=None, help="Comma list like 19:-1,24:-2. Defaults to current real5 thresholds.")
    ap.add_argument("--retain", type=float, default=0.90, help="Target full-trigger retention per actual CU QP.")
    ap.add_argument("--score", choices=("max_g_cov", "linear_trigger"), default="max_g_cov")
    ap.add_argument("--out-json", type=Path, required=True)
    ap.add_argument("--out-inc", type=Path, required=True)
    args = ap.parse_args()

    final_thresholds = parse_thresholds(args.final_threshold)
    buckets = sorted(final_thresholds)
    rows_by_qp: dict[int, list[tuple[float, bool, list[float]]]] = {qp: [] for qp in buckets}
    meta_counts: dict[int, list[int]] = {}

    total_rows = 0
    trigger_rows = 0
    for path in args.logs:
        with open_text(path) as handle:
            reader = csv.DictReader(handle)
            required = {"actualCuQp", "tableFound", "G1_cov", "G2_cov", "predRDGain1", "predRDGain2"}
            if args.score == "linear_trigger":
                required |= {
                    "W", "H", "latBin", "setIdx", "transpose", "sigma2", "qStep", "kIn", "outN",
                    "predRateGainBits1", "predRateGainBits2",
                    "tableZeroOutEnergy1", "tableZeroOutEnergy2",
                    "tableRetainedEnergy1", "tableRetainedEnergy2",
                }
            missing = sorted(required - set(reader.fieldnames or []))
            if missing:
                raise SystemExit(f"{path}: missing required columns: {', '.join(missing)}")
            for row in reader:
                if int(safe_float(row, "tableFound", 0.0)) != 1:
                    continue
                actual_qp = int(round(safe_float(row, "actualCuQp", safe_float(row, "QP", 0.0))))
                qp_bucket = nearest_qp(actual_qp, buckets)
                g1 = safe_float(row, "G1_cov")
                g2 = safe_float(row, "G2_cov")
                pred1 = safe_float(row, "predRDGain1")
                pred2 = safe_float(row, "predRDGain2")
                if not all(math.isfinite(v) for v in (g1, g2, pred1, pred2)):
                    continue
                score = max(g1, g2)
                trigger = max(pred1, pred2) <= final_thresholds[qp_bucket]
                rows_by_qp[qp_bucket].append((score, trigger, cheap_features(row)))
                if {"W", "H", "latBin", "setIdx", "transpose"}.issubset(row):
                    meta_key = pack_meta_key(
                        qp_bucket,
                        int(round(safe_float(row, "W", 0.0))),
                        int(round(safe_float(row, "H", 0.0))),
                        int(round(safe_float(row, "latBin", 0.0))),
                        int(round(safe_float(row, "setIdx", 0.0))),
                        int(round(safe_float(row, "transpose", 0.0))),
                    )
                    counts = meta_counts.setdefault(meta_key, [0, 0])
                    counts[0] += 1
                    counts[1] += int(trigger)
                total_rows += 1
                trigger_rows += int(trigger)

    by_qp: dict[str, dict[str, float | int]] = {}
    thresholds: list[float] = []
    means: list[list[float]] = []
    scales: list[list[float]] = []
    coeffs: list[list[float]] = []
    intercepts: list[float] = []
    for qp in buckets:
        rows = rows_by_qp[qp]
        if args.score == "linear_trigger":
            x = np.array([feat for _, _, feat in rows], dtype=np.float64)
            y = np.array([1.0 if trigger else 0.0 for _, trigger, _ in rows], dtype=np.float64)
            mean, scale, coef, intercept, scores_np = fit_weighted_ridge(x, y)
            scores = [float(v) for v in scores_np]
            trigger_scores = sorted(score for score, (_, trigger, _) in zip(scores, rows) if trigger)
            threshold = quantile(trigger_scores, 1.0 - args.retain)
            pass_flags = [score >= threshold for score in scores]
            means.append([float(v) for v in mean])
            scales.append([float(v) for v in scale])
            coeffs.append([float(v) for v in coef])
            intercepts.append(intercept)
        else:
            trigger_scores = sorted(score for score, trigger, _ in rows if trigger)
            threshold = quantile(trigger_scores, args.retain)
            pass_flags = [score <= threshold for score, _, _ in rows]
            means.append([0.0 for _ in FEATURE_NAMES])
            scales.append([1.0 for _ in FEATURE_NAMES])
            coeffs.append([0.0 for _ in FEATURE_NAMES])
            intercepts.append(0.0)
        thresholds.append(threshold)
        pass_count = sum(1 for flag in pass_flags if flag)
        trigger_count = len(trigger_scores)
        retained = sum(1 for flag, (_, trigger, _) in zip(pass_flags, rows) if flag and trigger)
        non_trigger = len(rows) - trigger_count
        non_trigger_pass = sum(1 for flag, (_, trigger, _) in zip(pass_flags, rows) if flag and not trigger)
        by_qp[str(qp)] = {
            "rows": len(rows),
            "trigger_rows": trigger_count,
            "threshold": threshold,
            "pass_rows": pass_count,
            "pass_rate": pass_count / len(rows) if rows else 0.0,
            "trigger_retain_rate": retained / trigger_count if trigger_count else 1.0,
            "non_trigger_pass_rate": non_trigger_pass / non_trigger if non_trigger else 0.0,
        }

    result = {
        "score": args.score,
        "retain_target": args.retain,
        "rows": total_rows,
        "trigger_rows": trigger_rows,
        "final_thresholds": {str(k): v for k, v in final_thresholds.items()},
        "feature_names": FEATURE_NAMES,
        "by_qp": by_qp,
    }
    selected_meta_keys: list[int] = []
    if trigger_rows > 0 and meta_counts:
      ordered_meta = sorted(
          meta_counts.items(),
          key=lambda kv: (kv[1][1] / max(1, kv[1][0]), kv[1][1], -kv[1][0]),
          reverse=True,
      )
      retained_triggers = 0
      target_triggers = math.ceil(args.retain * trigger_rows)
      for key, counts in ordered_meta:
          if counts[1] <= 0:
              continue
          selected_meta_keys.append(key)
          retained_triggers += counts[1]
          if retained_triggers >= target_triggers:
              break
      selected_set = set(selected_meta_keys)
      meta_pass_rows = sum(counts[0] for key, counts in meta_counts.items() if key in selected_set)
      meta_retained_triggers = sum(counts[1] for key, counts in meta_counts.items() if key in selected_set)
      meta_non_trigger = total_rows - trigger_rows
      meta_non_trigger_pass = meta_pass_rows - meta_retained_triggers
      result["meta_gate"] = {
          "keys": len(selected_meta_keys),
          "pass_rows": meta_pass_rows,
          "pass_rate": meta_pass_rows / total_rows if total_rows else 0.0,
          "trigger_retain_rate": meta_retained_triggers / trigger_rows if trigger_rows else 1.0,
          "non_trigger_pass_rate": meta_non_trigger_pass / meta_non_trigger if meta_non_trigger else 0.0,
      }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    inc = [
        "// Auto-generated by tools/lard_lfnst/fit_lard_lfnst_skip18_cheap_gate.py",
        f"#define LARD_LFNST_SKIP18_CHEAP_GATE_QP_BUCKETS {len(buckets)}",
        f"#define LARD_LFNST_SKIP18_CHEAP_GATE_FEATURES {len(FEATURE_NAMES)}",
        f"static const int LARD_LFNST_SKIP18_CHEAP_GATE_QP[{len(buckets)}] = {{ {', '.join(str(qp) for qp in buckets)} }};",
        f"static const double LARD_LFNST_SKIP18_CHEAP_GATE_THRESHOLD[{len(buckets)}] = {{ {format_cpp_array(thresholds)} }};",
    ]
    inc.append(f"static const double LARD_LFNST_SKIP18_CHEAP_GATE_INTERCEPT[{len(buckets)}] = {{ {format_cpp_array(intercepts)} }};")
    inc.append(f"static const double LARD_LFNST_SKIP18_CHEAP_GATE_MEAN[{len(buckets)}][{len(FEATURE_NAMES)}] = {{")
    for row in means:
        inc.append(f"  {{ {format_cpp_array(row)} }},")
    inc.append("};")
    inc.append(f"static const double LARD_LFNST_SKIP18_CHEAP_GATE_SCALE[{len(buckets)}][{len(FEATURE_NAMES)}] = {{")
    for row in scales:
        inc.append(f"  {{ {format_cpp_array(row)} }},")
    inc.append("};")
    inc.append(f"static const double LARD_LFNST_SKIP18_CHEAP_GATE_COEFF[{len(buckets)}][{len(FEATURE_NAMES)}] = {{")
    for row in coeffs:
        inc.append(f"  {{ {format_cpp_array(row)} }},")
    inc.append("};")
    inc.append(f"#define LARD_LFNST_SKIP18_META_GATE_KEYS {len(selected_meta_keys)}")
    inc.append(f"static const long long LARD_LFNST_SKIP18_META_GATE_KEY[{len(selected_meta_keys)}] = {{")
    if selected_meta_keys:
        for key in sorted(selected_meta_keys):
            inc.append(f"  {key}LL,")
    inc.append("};")
    inc.append("")
    args.out_inc.parent.mkdir(parents=True, exist_ok=True)
    args.out_inc.write_text("\n".join(inc), encoding="utf-8")


if __name__ == "__main__":
    main()
