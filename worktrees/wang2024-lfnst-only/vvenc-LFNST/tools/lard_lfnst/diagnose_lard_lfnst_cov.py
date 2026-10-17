#!/usr/bin/env python3
"""Detailed diagnostics for Skip15 covariance prediction logs."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np


def corr(left: list[float], right: list[float]) -> float:
    if len(left) < 2:
        return 0.0
    left_np = np.asarray(left, dtype=np.float64)
    right_np = np.asarray(right, dtype=np.float64)
    if np.std(left_np) == 0.0 or np.std(right_np) == 0.0:
        return 0.0
    return float(np.corrcoef(left_np, right_np)[0, 1])


def auc(scores: list[float], labels: list[int]) -> float:
    order = np.argsort(np.asarray(scores), kind="mergesort")
    labels_np = np.asarray(labels, dtype=np.int8)[order]
    scores_np = np.asarray(scores)[order]
    positives = int(labels_np.sum())
    negatives = len(labels_np) - positives
    if not positives or not negatives:
        return 0.0
    wins = 0.0
    negatives_before = 0
    index = 0
    while index < len(labels_np):
        end = index + 1
        while end < len(labels_np) and scores_np[end] == scores_np[index]:
            end += 1
        tied_positive = int(labels_np[index:end].sum())
        tied_negative = end - index - tied_positive
        wins += tied_positive * (negatives_before + 0.5 * tied_negative)
        negatives_before += tied_negative
        index = end
    return wins / (positives * negatives)


def quantiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    array = np.asarray(values, dtype=np.float64)
    return {
        "mean": float(array.mean()),
        "p05": float(np.quantile(array, 0.05)),
        "p25": float(np.quantile(array, 0.25)),
        "median": float(np.quantile(array, 0.5)),
        "p75": float(np.quantile(array, 0.75)),
        "p95": float(np.quantile(array, 0.95)),
    }


def safe_float(row: dict[str, str], name: str, default: float = math.nan) -> float:
    value = row.get(name, "")
    if value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def metric_block(rows: list[tuple[float, float, float, float, int]]) -> dict[str, object]:
    if not rows:
        return {"rows": 0}
    g1 = [row[0] for row in rows]
    g2 = [row[1] for row in rows]
    dj1 = [row[2] for row in rows]
    dj2 = [row[3] for row in rows]
    best = [row[4] for row in rows]
    return {
        "rows": len(rows),
        "final_counts": dict(Counter(best)),
        "g1_positive_rate": sum(value > 0.0 for value in g1) / len(rows),
        "g2_positive_rate": sum(value > 0.0 for value in g2) / len(rows),
        "dj1_positive_rate": sum(value > 0.0 for value in dj1) / len(rows),
        "dj2_positive_rate": sum(value > 0.0 for value in dj2) / len(rows),
        "any_nonzero_gain_rate": sum(max(a, b) > 0.0 for a, b in zip(dj1, dj2)) / len(rows),
        "corr_g1_dj1": corr(g1, dj1),
        "corr_g2_dj2": corr(g2, dj2),
        "auc_g1": auc(g1, [int(value > 0.0) for value in dj1]),
        "auc_g2": auc(g2, [int(value > 0.0) for value in dj2]),
        "sign_accuracy_g1": sum((a > 0.0) == (b > 0.0) for a, b in zip(g1, dj1)) / len(rows),
        "sign_accuracy_g2": sum((a > 0.0) == (b > 0.0) for a, b in zip(g2, dj2)) / len(rows),
        "ranking_accuracy": sum((a > b) == (c > d) for a, b, c, d in zip(g1, g2, dj1, dj2)) / len(rows),
        "g1": quantiles(g1),
        "g2": quantiles(g2),
        "delta_j1": quantiles(dj1),
        "delta_j2": quantiles(dj2),
        "abs_g_over_abs_delta_j1_median": float(
            np.median([abs(a) / max(abs(b), 1e-9) for a, b in zip(g1, dj1)])
        ),
        "abs_g_over_abs_delta_j2_median": float(
            np.median([abs(a) / max(abs(b), 1e-9) for a, b in zip(g2, dj2)])
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--out-json", type=Path, required=True)
    args = parser.parse_args()

    total_by_qp = Counter()
    found_by_qp = Counter()
    missing_sizes: Counter[tuple[int, int]] = Counter()
    complete: list[tuple[float, float, float, float, int]] = []
    by_qp: dict[int, list[tuple[float, float, float, float, int]]] = defaultdict(list)
    by_lat: dict[int, list[tuple[float, float, float, float, int]]] = defaultdict(list)
    by_size: dict[str, list[tuple[float, float, float, float, int]]] = defaultdict(list)
    by_set: dict[int, list[tuple[float, float, float, float, int]]] = defaultdict(list)
    by_transpose: dict[int, list[tuple[float, float, float, float, int]]] = defaultdict(list)
    by_final_score: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    actual_sum = np.zeros((2, 16), dtype=np.float64)
    predicted_sum = np.zeros((2, 16), dtype=np.float64)
    variance_count = np.zeros((2, 16), dtype=np.int64)
    rd_residuals: list[float] = []
    rd_candidate: list[dict[str, list[float]]] = [
        defaultdict(list),
        defaultdict(list),
    ]

    for path in args.logs:
        with gzip.open(path, "rt", newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                qp = int(row["QP"])
                width = int(row["W"])
                height = int(row["H"])
                total_by_qp[qp] += 1
                if int(row["tableFound"]) == 0:
                    missing_sizes[(width, height)] += 1
                    continue
                found_by_qp[qp] += 1

                for candidate in (0, 1):
                    if int(row[f"actualValid{candidate + 1}"]) == 0:
                        continue
                    for index in range(16):
                        actual_sum[candidate, index] += float(row[f"actualY{candidate + 1}Sq_{index:02d}"])
                        predicted_sum[candidate, index] += float(row[f"predVarY{candidate + 1}_{index:02d}"])
                        variance_count[candidate, index] += 1

                costs = [float(row[name]) for name in ("J0", "J1", "J2")]
                if any(not math.isfinite(value) or abs(value) >= 1e300 for value in costs):
                    continue
                dist_costs = [safe_float(row, f"distCost{idx}") for idx in range(3)]
                rate_costs = [safe_float(row, f"rateCost{idx}") for idx in range(3)]
                if all(math.isfinite(value) for value in dist_costs + rate_costs):
                    for candidate in (1, 2):
                        delta_total = costs[0] - costs[candidate]
                        delta_dist = dist_costs[0] - dist_costs[candidate]
                        delta_rate = rate_costs[0] - rate_costs[candidate]
                        rd_residuals.append(delta_total - delta_dist - delta_rate)
                        values_rd = rd_candidate[candidate - 1]
                        values_rd["delta_total"].append(delta_total)
                        values_rd["delta_dist_cost"].append(delta_dist)
                        values_rd["delta_rate_cost"].append(delta_rate)
                        values_rd["g"].append(float(row[f"G{candidate}_cov"]))
                        zero_out = safe_float(row, f"zeroOutEnergy{candidate}")
                        retained = safe_float(row, f"retainedEnergyRatio{candidate}")
                        if math.isfinite(zero_out):
                            values_rd["zero_out_energy"].append(zero_out)
                            values_rd["distortion_loss_for_zero_out"].append(-delta_dist)
                        if math.isfinite(retained):
                            values_rd["retained_energy_ratio"].append(retained)
                        predicted_rate_gain = safe_float(row, f"predRateGainBits{candidate}")
                        if math.isfinite(predicted_rate_gain):
                            values_rd["pred_rate_gain_bits"].append(predicted_rate_gain)
                            values_rd["actual_rate_gain_bits"].append(delta_rate / float(1 << 15))
                values = (
                    float(row["G1_cov"]),
                    float(row["G2_cov"]),
                    costs[0] - costs[1],
                    costs[0] - costs[2],
                    int(row["bestIdx"]),
                )
                complete.append(values)
                by_qp[qp].append(values)
                by_lat[int(row["latBin"])].append(values)
                by_size[f"{width}x{height}"].append(values)
                by_set[int(row["setIdx"])].append(values)
                by_transpose[int(row["transpose"])].append(values)
                for name, value in zip(("g1", "g2", "dj1", "dj2"), values[:4]):
                    by_final_score[values[4]][name].append(value)

    variance = {}
    for candidate in (0, 1):
        coeff = []
        for index in range(16):
            ratio = (
                actual_sum[candidate, index] / predicted_sum[candidate, index]
                if predicted_sum[candidate, index] > 0.0
                else 0.0
            )
            coeff.append(
                {
                    "index": index,
                    "samples": int(variance_count[candidate, index]),
                    "actual_over_predicted": float(ratio),
                }
            )
        variance[f"candidate{candidate + 1}"] = {
            "overall_actual_over_predicted": float(
                actual_sum[candidate].sum() / predicted_sum[candidate].sum()
                if predicted_sum[candidate].sum() > 0.0
                else 0.0
            ),
            "coefficient_ratios": coeff,
            "ratio_coefficient_of_variation": float(
                np.std([item["actual_over_predicted"] for item in coeff])
                / np.mean([item["actual_over_predicted"] for item in coeff])
                if np.mean([item["actual_over_predicted"] for item in coeff]) > 0.0
                else 0.0
            ),
        }

    rd_decomposition: dict[str, object] = {
        "rows": len(rd_residuals) // 2,
        "max_abs_residual": max((abs(value) for value in rd_residuals), default=0.0),
    }
    for candidate in (0, 1):
        values_rd = rd_candidate[candidate]
        block: dict[str, object] = {
            "delta_total": quantiles(values_rd["delta_total"]),
            "delta_dist_cost": quantiles(values_rd["delta_dist_cost"]),
            "delta_rate_cost": quantiles(values_rd["delta_rate_cost"]),
            "delta_total_mean": float(np.mean(values_rd["delta_total"])),
            "delta_dist_cost_mean": float(np.mean(values_rd["delta_dist_cost"])),
            "delta_rate_cost_mean": float(np.mean(values_rd["delta_rate_cost"])),
            "corr_g_total": corr(values_rd["g"], values_rd["delta_total"]),
            "corr_g_dist_cost": corr(values_rd["g"], values_rd["delta_dist_cost"]),
            "corr_g_rate_cost": corr(values_rd["g"], values_rd["delta_rate_cost"]),
        }
        if values_rd["zero_out_energy"]:
            block["zero_out_energy"] = quantiles(values_rd["zero_out_energy"])
            block["corr_zero_out_distortion_loss"] = corr(
                values_rd["zero_out_energy"], values_rd["distortion_loss_for_zero_out"]
            )
        if values_rd["retained_energy_ratio"]:
            block["retained_energy_ratio"] = quantiles(values_rd["retained_energy_ratio"])
        if values_rd["pred_rate_gain_bits"]:
            block["pred_rate_gain_bits"] = quantiles(values_rd["pred_rate_gain_bits"])
            block["actual_rate_gain_bits"] = quantiles(values_rd["actual_rate_gain_bits"])
            block["corr_predicted_actual_rate_gain"] = corr(
                values_rd["pred_rate_gain_bits"], values_rd["actual_rate_gain_bits"]
            )
        rd_decomposition[f"candidate{candidate + 1}"] = block

    result = {
        "input_logs": [str(path) for path in args.logs],
        "rows_total_by_qp": dict(total_by_qp),
        "table_found_by_qp": dict(found_by_qp),
        "table_coverage_by_qp": {
            str(qp): found_by_qp[qp] / total_by_qp[qp] for qp in sorted(total_by_qp)
        },
        "missing_table_sizes": {
            f"{width}x{height}": count for (width, height), count in missing_sizes.most_common()
        },
        "overall": metric_block(complete),
        "by_qp": {str(key): metric_block(value) for key, value in sorted(by_qp.items())},
        "by_lat_bin": {str(key): metric_block(value) for key, value in sorted(by_lat.items())},
        "by_size": {
            key: metric_block(value)
            for key, value in sorted(by_size.items(), key=lambda item: len(item[1]), reverse=True)
        },
        "by_set": {str(key): metric_block(value) for key, value in sorted(by_set.items())},
        "by_transpose": {
            str(key): metric_block(value) for key, value in sorted(by_transpose.items())
        },
        "score_by_final_idx": {
            str(final): {name: quantiles(values) for name, values in scores.items()}
            for final, scores in sorted(by_final_score.items())
        },
        "variance_calibration": variance,
        "rd_decomposition": rd_decomposition,
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["overall"], indent=2))


if __name__ == "__main__":
    main()
