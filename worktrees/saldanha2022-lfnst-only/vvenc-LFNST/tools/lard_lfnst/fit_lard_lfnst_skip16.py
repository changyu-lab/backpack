#!/usr/bin/env python3
"""Fit a cost-domain separated Skip16 predictor from Skip15 covariance logs."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from generate_lard_lfnst_cov_table import generate_entries


ENERGY_RATE_FEATURES = ("bias", "G", "QP", "log2W", "log2H", "isOutN8", "isSbSize8", "lfnstIdx")
ENERGY_DIST_FEATURES = (
    "bias",
    "G",
    "log1pZero",
    "log1pZeroQ",
    "zeroRatio",
    "log1pRetainedQ",
    "QP",
    "log2W",
    "log2H",
    "isOutN8",
    "isSbSize8",
    "lfnstIdx",
)
QUANT_STRUCT_RATE_FEATURES = ENERGY_RATE_FEATURES
QUANT_STRUCT_DIST_FEATURES = (
    "bias",
    "G",
    "log1pZeroQ",
    "zeroRatio",
    "log1pRetainedQ",
    "responseNnz",
    "responseZeroNnz",
    "responseLast",
    "responseSigDensity",
    "responseHoleCount",
    "responseLogLevelSum",
    "deltaNnz",
    "deltaLast",
    "QP",
    "log2W",
    "log2H",
    "isOutN8",
    "isSbSize8",
    "lfnstIdx",
)


@dataclass
class CandidateSample:
    row_id: int
    qp: int
    candidate: int
    rate_features: list[float]
    dist_features: list[float]
    true_rate_gain: float
    true_dist_loss: float
    true_rd_gain: float


def open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", newline="", encoding="utf-8")
    return path.open("r", newline="", encoding="utf-8")


def safe_float(row: dict[str, str], key: str, default: float = math.nan) -> float:
    value = row.get(key, "")
    if value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def finite_costs(values: Iterable[float]) -> bool:
    return all(math.isfinite(value) and abs(value) < 1e300 for value in values)


def build_table_energy_lookup(rom_lfnst: Path | None) -> dict[tuple[int, int, int, int, int], tuple[np.ndarray, np.ndarray]]:
    if rom_lfnst is None:
        return {}
    lookup: dict[tuple[int, int, int, int, int], tuple[np.ndarray, np.ndarray]] = {}
    for entry in generate_entries(rom_lfnst):
        key = (
            int(entry["latBin"]),
            int(entry["W"]),
            int(entry["H"]),
            int(entry["setIdx"]),
            int(entry["transpose"]),
        )
        lookup[key] = (
            np.asarray(entry["expZeroEnergy"], dtype=np.float64),
            np.asarray(entry["expRetainedEnergy"], dtype=np.float64),
        )
    return lookup


def build_samples(
    logs: list[Path],
    energy_source: str = "posterior",
    feature_set: str = "energy",
    table_lookup: dict[tuple[int, int, int, int, int], tuple[np.ndarray, np.ndarray]] | None = None,
) -> tuple[list[CandidateSample], dict[str, int]]:
    samples: list[CandidateSample] = []
    counters = defaultdict(int)
    row_id = 0
    for path in logs:
        with open_text(path) as handle:
            for row in csv.DictReader(handle):
                counters["rows_total"] += 1
                if int(float(row.get("tableFound", "0") or 0)) == 0:
                    counters["rows_table_missing"] += 1
                    continue
                costs = [safe_float(row, key) for key in ("J0", "J1", "J2")]
                dist_costs = [safe_float(row, f"distCost{idx}") for idx in range(3)]
                rate_costs = [safe_float(row, f"rateCost{idx}") for idx in range(3)]
                if not finite_costs(costs + dist_costs + rate_costs):
                    counters["rows_incomplete_rdo"] += 1
                    continue

                qp = int(float(row.get("actualCuQp", row.get("QP", "0")) or 0))
                width = max(1, int(float(row.get("W", "1") or 1)))
                height = max(1, int(float(row.get("H", "1") or 1)))
                out_n = int(float(row.get("outN", "16") or 16))
                k_in = int(float(row.get("kIn", "48") or 48))
                qstep = safe_float(row, "qStep")
                if not math.isfinite(qstep) or qstep <= 0.0:
                    qstep = 2.0 ** ((qp - 4.0) / 6.0)
                qstep2 = qstep * qstep
                sigma2 = max(0.0, safe_float(row, "sigma2", 0.0))
                log2w = math.log2(width)
                log2h = math.log2(height)
                is_out8 = 1.0 if out_n == 8 else 0.0
                is_sb8 = 1.0 if k_in == 48 else 0.0
                table_energy = None
                if energy_source == "table":
                    key = (
                        int(float(row.get("latBin", "-1") or -1)),
                        width,
                        height,
                        int(float(row.get("setIdx", "-1") or -1)),
                        int(float(row.get("transpose", "0") or 0)),
                    )
                    table_energy = (table_lookup or {}).get(key)
                    if table_energy is None:
                        counters["rows_table_energy_missing"] += 1
                        continue

                for candidate in (1, 2):
                    g = safe_float(row, f"G{candidate}_cov")
                    if energy_source == "table":
                        assert table_energy is not None
                        zero = max(0.0, sigma2 * float(table_energy[0][candidate - 1]))
                        retained = max(0.0, sigma2 * float(table_energy[1][candidate - 1]))
                    elif energy_source == "response":
                        zero = max(0.0, safe_float(row, f"responseZeroOutEnergy{candidate}", 0.0))
                        retained = max(0.0, safe_float(row, f"responseRetainedEnergy{candidate}", 0.0))
                    else:
                        zero = max(0.0, safe_float(row, f"zeroOutEnergy{candidate}", 0.0))
                        retained = max(0.0, safe_float(row, f"outputEnergy{candidate}", 0.0))
                    if not math.isfinite(g):
                        continue
                    zero_ratio = zero / (zero + retained + 1e-12)
                    response_nnz = safe_float(row, f"responseNnz{candidate}", math.nan)
                    response_zero_nnz = safe_float(row, f"responseZeroNnz{candidate}", math.nan)
                    response_last = safe_float(row, f"responseLast{candidate}", math.nan)
                    response_density = safe_float(row, f"responseSigDensity{candidate}", math.nan)
                    response_holes = safe_float(row, f"responseHoleCount{candidate}", math.nan)
                    response_log_level = safe_float(row, f"responseLogLevelSum{candidate}", math.nan)
                    base_nnz = safe_float(row, "baseNnz", math.nan)
                    base_last = safe_float(row, "baseLast", math.nan)
                    if feature_set == "quant-struct":
                        required = [
                            response_nnz,
                            response_zero_nnz,
                            response_last,
                            response_density,
                            response_holes,
                            response_log_level,
                            base_nnz,
                            base_last,
                        ]
                        if not all(math.isfinite(value) for value in required):
                            missing = [
                                name for name, value in (
                                    (f"responseNnz{candidate}", response_nnz),
                                    (f"responseZeroNnz{candidate}", response_zero_nnz),
                                    (f"responseLast{candidate}", response_last),
                                    (f"responseSigDensity{candidate}", response_density),
                                    (f"responseHoleCount{candidate}", response_holes),
                                    (f"responseLogLevelSum{candidate}", response_log_level),
                                    ("baseNnz", base_nnz),
                                    ("baseLast", base_last),
                                )
                                if not math.isfinite(value)
                            ]
                            raise ValueError(
                                "quant-struct feature-set requires missing CSV columns: " + ", ".join(missing)
                            )
                    true_rate_gain = rate_costs[0] - rate_costs[candidate]
                    true_dist_loss = dist_costs[candidate] - dist_costs[0]
                    true_rd_gain = costs[0] - costs[candidate]
                    rate_features = [1.0, g, float(qp), log2w, log2h, is_out8, is_sb8, float(candidate)]
                    if feature_set == "quant-struct":
                        response_retained_nnz = safe_float(row, f"responseRetainedNnz{candidate}", 0.0)
                        dist_features = [
                            1.0,
                            g,
                            math.log1p(zero / (qstep2 + 1e-12)),
                            zero_ratio,
                            math.log1p(retained / (qstep2 + 1e-12)),
                            response_nnz,
                            response_zero_nnz,
                            response_last,
                            response_density,
                            response_holes,
                            response_log_level,
                            response_nnz - base_nnz,
                            response_last - base_last,
                            float(qp),
                            log2w,
                            log2h,
                            is_out8,
                            is_sb8,
                            float(candidate),
                        ]
                        _ = response_retained_nnz
                    else:
                        dist_features = [
                            1.0,
                            g,
                            math.log1p(zero),
                            math.log1p(zero / (qstep2 + 1e-12)),
                            zero_ratio,
                            math.log1p(retained / (qstep2 + 1e-12)),
                            float(qp),
                            log2w,
                            log2h,
                            is_out8,
                            is_sb8,
                            float(candidate),
                        ]
                    samples.append(
                        CandidateSample(
                            row_id=row_id,
                            qp=qp,
                            candidate=candidate,
                            rate_features=rate_features,
                            dist_features=dist_features,
                            true_rate_gain=true_rate_gain,
                            true_dist_loss=true_dist_loss,
                            true_rd_gain=true_rd_gain,
                        )
                    )
                row_id += 1
                counters["rows_complete"] += 1
    return samples, dict(counters)


def fit_ridge(features: np.ndarray, target: np.ndarray, ridge: float) -> np.ndarray:
    if len(target) == 0:
        raise ValueError("cannot fit ridge model with no samples")
    scale = np.ones(features.shape[1], dtype=np.float64)
    mean = np.zeros(features.shape[1], dtype=np.float64)
    if features.shape[1] > 1:
        mean[1:] = features[:, 1:].mean(axis=0)
        scale[1:] = features[:, 1:].std(axis=0)
        scale[scale == 0.0] = 1.0
    normalized = (features - mean) / scale
    normalized[:, 0] = 1.0
    penalty = np.eye(features.shape[1], dtype=np.float64) * ridge
    penalty[0, 0] = 0.0
    coeff_norm = np.linalg.solve(normalized.T @ normalized + penalty, normalized.T @ target)
    coeff = coeff_norm / scale
    coeff[0] = coeff_norm[0] - float(np.sum(coeff_norm[1:] * mean[1:] / scale[1:]))
    return coeff


def corr(left: list[float], right: list[float]) -> float:
    if len(left) < 2:
        return 0.0
    left_np = np.asarray(left, dtype=np.float64)
    right_np = np.asarray(right, dtype=np.float64)
    if np.std(left_np) == 0.0 or np.std(right_np) == 0.0:
        return 0.0
    return float(np.corrcoef(left_np, right_np)[0, 1])


def quantiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    array = np.asarray(values, dtype=np.float64)
    return {
        "mean": float(array.mean()),
        "p05": float(np.quantile(array, 0.05)),
        "median": float(np.quantile(array, 0.50)),
        "p95": float(np.quantile(array, 0.95)),
    }


def split_samples(samples: list[CandidateSample]) -> tuple[list[CandidateSample], list[CandidateSample]]:
    train = [sample for sample in samples if sample.row_id % 5 != 0]
    valid = [sample for sample in samples if sample.row_id % 5 == 0]
    if not train or not valid:
        return samples, samples
    return train, valid


def fit_models(samples: list[CandidateSample], ridge: float) -> dict[int, dict[str, np.ndarray]]:
    models: dict[int, dict[str, np.ndarray]] = {}
    for candidate in (1, 2):
        subset = [sample for sample in samples if sample.candidate == candidate]
        rate_x = np.asarray([sample.rate_features for sample in subset], dtype=np.float64)
        dist_x = np.asarray([sample.dist_features for sample in subset], dtype=np.float64)
        rate_y = np.asarray([sample.true_rate_gain for sample in subset], dtype=np.float64)
        dist_y = np.asarray([max(0.0, sample.true_dist_loss) for sample in subset], dtype=np.float64)
        models[candidate] = {
            "rate": fit_ridge(rate_x, rate_y, ridge),
            "dist": fit_ridge(dist_x, dist_y, ridge),
        }
    return models


def fit_model_bundle(samples: list[CandidateSample], ridge: float, calibration: str) -> dict[str, object]:
    global_models = fit_models(samples, ridge)
    by_qp: dict[int, dict[int, dict[str, np.ndarray]]] = {}
    if calibration == "actual-qp":
        for qp in sorted({sample.qp for sample in samples}):
            subset = [sample for sample in samples if sample.qp == qp]
            if all(any(sample.candidate == candidate for sample in subset) for candidate in (1, 2)):
                by_qp[qp] = fit_models(subset, ridge)
    return {"global": global_models, "by_qp": by_qp}


def models_for_sample(sample: CandidateSample, model_bundle: dict[str, object]) -> dict[int, dict[str, np.ndarray]]:
    by_qp = model_bundle.get("by_qp", {})
    if isinstance(by_qp, dict) and by_qp:
        if sample.qp in by_qp:
            return by_qp[sample.qp]  # type: ignore[return-value]
        nearest_qp = min(by_qp, key=lambda qp: abs(int(qp) - sample.qp))
        return by_qp[nearest_qp]  # type: ignore[return-value]
    return model_bundle["global"]  # type: ignore[return-value]


def predict_sample(sample: CandidateSample, model_bundle: dict[str, object] | dict[int, dict[str, np.ndarray]]) -> tuple[float, float, float]:
    if "global" in model_bundle:
        models = models_for_sample(sample, model_bundle)  # type: ignore[arg-type]
    else:
        models = model_bundle  # type: ignore[assignment]
    model = models[sample.candidate]
    pred_rate = float(np.dot(np.asarray(sample.rate_features), model["rate"]))
    pred_dist = max(0.0, float(np.dot(np.asarray(sample.dist_features), model["dist"])))
    return pred_rate, pred_dist, pred_rate - pred_dist


def metric_block(samples: list[CandidateSample], models: dict[str, object] | dict[int, dict[str, np.ndarray]]) -> dict[str, object]:
    pred_rate: list[float] = []
    pred_dist: list[float] = []
    pred_rd: list[float] = []
    true_rate: list[float] = []
    true_dist: list[float] = []
    true_rd: list[float] = []
    for sample in samples:
        pr, pd, pj = predict_sample(sample, models)
        pred_rate.append(pr)
        pred_dist.append(pd)
        pred_rd.append(pj)
        true_rate.append(sample.true_rate_gain)
        true_dist.append(sample.true_dist_loss)
        true_rd.append(sample.true_rd_gain)
    positive = [value > 0.0 for value in true_rd]
    predicted_positive = [value > 0.0 for value in pred_rd]
    tp = sum(a and b for a, b in zip(positive, predicted_positive))
    fn = sum(a and not b for a, b in zip(positive, predicted_positive))
    tn = sum((not a) and (not b) for a, b in zip(positive, predicted_positive))
    fp = sum((not a) and b for a, b in zip(positive, predicted_positive))
    return {
        "rows": len(samples),
        "corr_pred_rate_true_rate": corr(pred_rate, true_rate),
        "corr_pred_dist_true_dist": corr(pred_dist, true_dist),
        "corr_pred_rd_true_rd": corr(pred_rd, true_rd),
        "true_rd": quantiles(true_rd),
        "pred_rd": quantiles(pred_rd),
        "positive_rd_recall": tp / max(tp + fn, 1),
        "negative_rd_precision": tn / max(tn + fn, 1),
        "positive_count": sum(positive),
        "predicted_positive_count": sum(predicted_positive),
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
    }


TARGET_SKIP_RATES = (0.01, 0.02, 0.03, 0.04, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50)


def skip_only_sweep(samples: list[CandidateSample], models: dict[str, object] | dict[int, dict[str, np.ndarray]], qp: int | None = None) -> list[dict[str, float]]:
    by_row: dict[int, list[CandidateSample]] = defaultdict(list)
    for sample in samples:
        by_row[sample.row_id].append(sample)
    row_scores: list[tuple[float, float]] = []
    for pair in by_row.values():
        if len(pair) != 2:
            continue
        pred_best = max(predict_sample(sample, models)[2] for sample in pair)
        true_best = max(sample.true_rd_gain for sample in pair)
        row_scores.append((pred_best, true_best))
    if not row_scores:
        return []
    pred_values = np.asarray([item[0] for item in row_scores], dtype=np.float64)
    thresholds = [(rate, float(np.quantile(pred_values, rate))) for rate in TARGET_SKIP_RATES]
    thresholds.append((math.nan, 0.0))
    total_positive_gain = sum(max(0.0, true_best) for _, true_best in row_scores)
    sweep = []
    seen: set[tuple[float, float]] = set()
    for target_rate, threshold in thresholds:
        key = (target_rate, threshold)
        if key in seen:
            continue
        seen.add(key)
        skipped = [(pred, true) for pred, true in row_scores if pred <= threshold]
        missed = [max(0.0, true) for _, true in skipped if true > 0.0]
        false_skip = len(missed)
        row = {
            "target_skip_rate": None if math.isnan(target_rate) else target_rate,
            "threshold": threshold,
            "skip_rate": len(skipped) / len(row_scores),
            "false_skip_rate": false_skip / len(row_scores),
            "false_skip_rate_all": false_skip / len(row_scores),
            "false_skip_rate_skipped": false_skip / max(len(skipped), 1),
            "missed_positive_gain_sum": float(sum(missed)),
            "missed_positive_gain_mean": float(np.mean(missed)) if missed else 0.0,
            "missed_positive_gain_p95": float(np.quantile(missed, 0.95)) if missed else 0.0,
            "missed_gain_ratio": float(sum(missed) / max(total_positive_gain, 1e-12)),
            "missed_positive_gain_ratio": float(sum(missed) / max(total_positive_gain, 1e-12)),
        }
        if qp is not None:
            row["QP"] = qp
        sweep.append(row)
    return sweep


def skip_only_sweep_by_qp(samples: list[CandidateSample], models: dict[str, object] | dict[int, dict[str, np.ndarray]]) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for qp in sorted({sample.qp for sample in samples}):
        rows.extend(skip_only_sweep([sample for sample in samples if sample.qp == qp], models, qp))
    return rows


def write_threshold_csv(path: Path, rows: list[dict[str, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["QP", "target_skip_rate", "threshold", "false_skip_rate", "missed_gain_ratio"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            if row.get("target_skip_rate") is None:
                continue
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def write_inc(
    path: Path,
    model_bundle: dict[str, object] | dict[int, dict[str, np.ndarray]],
    cpp_prefix: str,
    rate_features: tuple[str, ...],
    dist_features: tuple[str, ...],
) -> None:
    def array(name: str, coeffs: list[np.ndarray]) -> str:
        rows = []
        for coeff in coeffs:
            rows.append("  { " + ", ".join(f"{value:.17g}" for value in coeff) + " }")
        return f"static const double {name}[2][{len(coeffs[0])}] = {{\n" + ",\n".join(rows) + "\n};\n"

    def array_qp(name: str, qp_models: dict[int, dict[int, dict[str, np.ndarray]]], kind: str) -> str:
        blocks = []
        for qp in sorted(qp_models):
            rows = []
            for candidate in (1, 2):
                rows.append("    { " + ", ".join(f"{value:.17g}" for value in qp_models[qp][candidate][kind]) + " }")
            blocks.append("  {\n" + ",\n".join(rows) + "\n  }")
        width = len(next(iter(qp_models.values()))[1][kind]) if qp_models else (len(rate_features) if kind == "rate" else len(dist_features))
        return f"static const double {name}[{len(qp_models)}][2][{width}] = {{\n" + ",\n".join(blocks) + "\n};\n"

    if "global" in model_bundle:
        global_models = model_bundle["global"]  # type: ignore[assignment]
        qp_models = model_bundle.get("by_qp", {})  # type: ignore[assignment]
    else:
        global_models = model_bundle  # type: ignore[assignment]
        qp_models = {}
    text = []
    text.append("// Auto-generated by tools/lard_lfnst/fit_lard_lfnst_skip16.py.\n")
    text.append(f"#define {cpp_prefix}_RATE_FEATURES " + str(len(rate_features)) + "\n")
    text.append(f"#define {cpp_prefix}_DIST_FEATURES " + str(len(dist_features)) + "\n")
    text.append(f"#define {cpp_prefix}_QP_BUCKETS " + str(len(qp_models)) + "\n")
    if qp_models:
        text.append(
            f"static const int {cpp_prefix}_QP_BUCKET[{len(qp_models)}] = {{ "
            + ", ".join(str(qp) for qp in sorted(qp_models))
            + " };\n"
        )
    text.append(array(f"{cpp_prefix}_RATE_COEFF", [global_models[1]["rate"], global_models[2]["rate"]]))  # type: ignore[index]
    text.append(array(f"{cpp_prefix}_DIST_COEFF", [global_models[1]["dist"], global_models[2]["dist"]]))  # type: ignore[index]
    if qp_models:
        text.append(array_qp(f"{cpp_prefix}_RATE_COEFF_QP", qp_models, "rate"))  # type: ignore[arg-type]
        text.append(array_qp(f"{cpp_prefix}_DIST_COEFF_QP", qp_models, "dist"))  # type: ignore[arg-type]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(text), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-inc", type=Path)
    parser.add_argument("--ridge", type=float, default=1e-3)
    parser.add_argument("--energy-source", choices=("posterior", "table", "response"), default="posterior")
    parser.add_argument("--feature-set", choices=("energy", "quant-struct"), default="energy")
    parser.add_argument("--calibration", choices=("global", "actual-qp"), default="global")
    parser.add_argument("--out-threshold-csv", type=Path)
    parser.add_argument("--rom-lfnst", type=Path)
    parser.add_argument("--cpp-prefix", default="LARD_LFNST_SKIP16")
    args = parser.parse_args()

    rate_features = QUANT_STRUCT_RATE_FEATURES if args.feature_set == "quant-struct" else ENERGY_RATE_FEATURES
    dist_features = QUANT_STRUCT_DIST_FEATURES if args.feature_set == "quant-struct" else ENERGY_DIST_FEATURES
    table_lookup = build_table_energy_lookup(args.rom_lfnst) if args.energy_source == "table" else {}
    samples, counters = build_samples(args.logs, args.energy_source, args.feature_set, table_lookup)
    if not samples:
        raise SystemExit("no complete candidate samples found")
    train, valid = split_samples(samples)
    models = fit_model_bundle(train, args.ridge, args.calibration)
    global_models = models["global"]  # type: ignore[assignment]
    by_qp_models = models["by_qp"]  # type: ignore[assignment]
    threshold_rows = skip_only_sweep_by_qp(valid, models)
    result = {
        "input_logs": [str(path) for path in args.logs],
        "energy_source": args.energy_source,
        "feature_set": args.feature_set,
        "calibration": args.calibration,
        "counters": counters,
        "rate_features": rate_features,
        "dist_features": dist_features,
        "train": {
            "overall": metric_block(train, models),
            "by_qp": {
                str(qp): metric_block([sample for sample in train if sample.qp == qp], models)
                for qp in sorted({sample.qp for sample in train})
            },
        },
        "validation": {
            "overall": metric_block(valid, models),
            "by_qp": {
                str(qp): metric_block([sample for sample in valid if sample.qp == qp], models)
                for qp in sorted({sample.qp for sample in valid})
            },
        },
        "skip_only_sweep": skip_only_sweep(valid, models),
        "skip_only_sweep_by_qp": threshold_rows,
        "models": {
            str(candidate): {
                "rate": global_models[candidate]["rate"].tolist(),
                "dist": global_models[candidate]["dist"].tolist(),
            }
            for candidate in (1, 2)
        },
        "actual_qp_models": {
            str(qp): {
                str(candidate): {
                    "rate": by_qp_models[qp][candidate]["rate"].tolist(),
                    "dist": by_qp_models[qp][candidate]["dist"].tolist(),
                }
                for candidate in (1, 2)
            }
            for qp in sorted(by_qp_models)
        },
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.out_threshold_csv:
        write_threshold_csv(args.out_threshold_csv, threshold_rows)
    if args.out_inc:
        write_inc(args.out_inc, models, args.cpp_prefix, rate_features, dist_features)
    print(json.dumps(result["validation"]["overall"], indent=2))


if __name__ == "__main__":
    main()
