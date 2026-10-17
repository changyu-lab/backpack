#!/usr/bin/env python3
"""Calibrate and validate Skip21 Stage-3 covariance-QARD one-sided risk margin.

The Stage-3 model predicts a normalized lower-is-better-candidate margin
    pred = min(Jhat_1-J0, Jhat_2-J0) / |J0|.
Positive means both non-zero LFNST candidates are predicted worse than LFNST=0.
For each shadow sample with full RDO truth,
    true = min(J1-J0, J2-J0) / |J0|,
    error = pred - true.
A conservative lower bound is pred - q, where q is an upper quantile of error.
Real pruning is enabled only when pred - q >= 0.

Calibration is sequence-level by construction: each input CSV is assigned a label.
The default `sequence_max` margin takes the maximum per-sequence (1-alpha)
finite-sample upper quantile, preventing a long/easy sequence from dominating.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

BASE_STAGE12 = (
    "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=123 "
    "LardLfnst21Profile=5 LardLfnst21Stage2Profile=12 "
    "LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0 "
    "LardLfnst21Stage3Mode=0"
)

SELECTIVE_BASE_ABS_SUM_MIN = 256.0
SELECTIVE_R0_PER_AREA_MIN = 29697.1531


@dataclass
class Sample:
    sequence: str
    qp: int
    pred: float
    truth: float
    error: float
    rdo0: float
    rdo12: float
    eval_time: float
    out_n: int
    size_group: int
    width: int
    height: int
    base_abs_sum: float
    r0: float


def finite(x: float) -> bool:
    return math.isfinite(x) and abs(x) < 1e300


def f(row: dict[str, str], key: str, default: float = math.nan) -> float:
    try:
        return float(row[key])
    except (KeyError, ValueError, TypeError):
        return default


def i(row: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(row[key]))
    except (KeyError, ValueError, TypeError):
        return default


def parse_spec(spec: str) -> tuple[str, Path]:
    if "=" in spec:
        label, raw = spec.split("=", 1)
        if not label.strip():
            raise ValueError(f"empty sequence label in {spec!r}")
        return label.strip(), Path(raw)
    path = Path(spec)
    return path.stem, path


def load_csv(label: str, path: Path) -> list[Sample]:
    rows: list[Sample] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"covQard", "predMinNormQard", "J0", "J1", "J2"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise RuntimeError(f"{path}: missing QARD columns: {sorted(missing)}")
        for row in reader:
            if i(row, "covQard") != 1:
                continue
            j0, j1, j2 = f(row, "J0"), f(row, "J1"), f(row, "J2")
            pred = f(row, "predMinNormQard")
            if not finite(j0) or not finite(pred):
                continue
            valid = [v for v in (j1, j2) if finite(v)]
            if not valid:
                continue
            true = (min(valid) - j0) / max(1.0, abs(j0))
            if not finite(true):
                continue
            rows.append(
                Sample(
                    sequence=label,
                    qp=i(row, "QP", -1),
                    pred=pred,
                    truth=true,
                    error=pred - true,
                    rdo0=max(0.0, f(row, "rdoTime0", 0.0)),
                    rdo12=max(0.0, f(row, "rdoTime1", 0.0)) + max(0.0, f(row, "rdoTime2", 0.0)),
                    eval_time=max(0.0, f(row, "rdeEvalTime", 0.0)),
                    out_n=i(row, "outN", 0),
                    size_group=i(row, "sizeGroup", -1),
                    width=i(row, "w", 0),
                    height=i(row, "h", 0),
                    base_abs_sum=max(0.0, f(row, "baseAbsSum", 0.0)),
                    r0=max(0.0, f(row, "R0", 0.0)),
                )
            )
    if not rows:
        raise RuntimeError(f"{path}: no finite covariance-QARD shadow samples with RDO truth")
    return rows


def upper_order_quantile(values: Iterable[float], alpha: float) -> float:
    vals = sorted(v for v in values if finite(v))
    if not vals:
        raise RuntimeError("cannot calibrate an empty error set")
    # Split-conformal-style finite-sample upper quantile rank: ceil((n+1)(1-alpha)).
    rank1 = min(len(vals), max(1, math.ceil((len(vals) + 1) * (1.0 - alpha))))
    return vals[rank1 - 1]


def percentile(values: Iterable[float], p: float) -> float:
    vals = sorted(v for v in values if finite(v))
    if not vals:
        return math.nan
    k = min(len(vals) - 1, max(0, math.ceil(p * len(vals)) - 1))
    return vals[k]


def ranks(vals: list[float]) -> list[float]:
    order = sorted(range(len(vals)), key=vals.__getitem__)
    out = [0.0] * len(vals)
    pos = 0
    while pos < len(vals):
        end = pos + 1
        while end < len(vals) and vals[order[end]] == vals[order[pos]]:
            end += 1
        rank = 0.5 * (pos + 1 + end)
        for k in range(pos, end):
            out[order[k]] = rank
        pos = end
    return out


def pearson(a: list[float], b: list[float]) -> float:
    if len(a) < 2 or len(a) != len(b):
        return math.nan
    ma = sum(a) / len(a)
    mb = sum(b) / len(b)
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return math.nan
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def real_eligible(sample: Sample, profile: int) -> bool:
    if profile == 0:
        return sample.out_n == 16 and sample.width * sample.height >= 256
    if profile == 1:
        return sample.out_n == 16
    if profile == 2:
        return True
    raise ValueError(f"invalid profile {profile}")


def activation_pass(sample: Sample, profile: int) -> bool:
    if profile == 0:
        return True
    if profile == 1:
        area = sample.width * sample.height
        if area <= 0:
            return False
        return (
            sample.base_abs_sum >= SELECTIVE_BASE_ABS_SUM_MIN
            and sample.r0 / area >= SELECTIVE_R0_PER_AREA_MIN
        )
    raise ValueError(f"invalid activation profile {profile}")


def trimmed_mean(values: Iterable[float], trim: float = 0.01) -> float:
    vals = sorted(v for v in values if finite(v))
    if not vals:
        return math.nan
    k = int(len(vals) * trim)
    core = vals[k:len(vals)-k] if k > 0 and 2 * k < len(vals) else vals
    return sum(core) / len(core)


def evaluate(samples: list[Sample], margin: float, profile: int, activation_profile: int = 0) -> dict[str, object]:
    if not samples:
        return {"n": 0}
    eligible = [s for s in samples if real_eligible(s, profile)]
    activated = [s for s in eligible if activation_pass(s, activation_profile)]
    skip = [s for s in activated if s.pred - margin >= 0.0]
    wrong = [s for s in skip if s.truth < 0.0]
    violations = [s for s in eligible if s.truth < s.pred - margin]
    regrets = [max(0.0, -s.truth) for s in wrong]
    pred = [s.pred for s in eligible]
    truth = [s.truth for s in eligible]
    total_rdo12 = sum(s.rdo12 for s in eligible)
    saved_rdo12 = sum(s.rdo12 for s in skip)
    total_all_rdo = sum(s.rdo0 + s.rdo12 for s in eligible)
    total_eval = sum(s.eval_time for s in activated)
    net_saved = saved_rdo12 - total_eval
    eval_trim = trimmed_mean((s.eval_time for s in activated), 0.01) if activated else 0.0
    rdo12_trim = trimmed_mean((s.rdo12 for s in eligible), 0.01) if eligible else 0.0
    robust_net_fraction = ((len(skip) / len(eligible)) * rdo12_trim - eval_trim) / rdo12_trim if eligible and rdo12_trim > 0 else 0.0
    per_seq: dict[str, dict[str, float | int]] = {}
    for seq in sorted({s.sequence for s in samples}):
        subset_all = [s for s in samples if s.sequence == seq]
        subset = [s for s in subset_all if real_eligible(s, profile)]
        sa = [s for s in subset if activation_pass(s, activation_profile)]
        ss = [s for s in sa if s.pred - margin >= 0.0]
        sw = [s for s in ss if s.truth < 0.0]
        per_seq[seq] = {
            "n_all": len(subset_all),
            "n_eligible": len(subset),
            "activated_n": len(sa),
            "activation_rate": len(sa) / len(subset) if subset else 0.0,
            "skip_n": len(ss),
            "skip_rate": len(ss) / len(sa) if sa else 0.0,
            "conditional_prune_rate": len(ss) / len(sa) if sa else 0.0,
            "prune_rate_over_eligible": len(ss) / len(subset) if subset else 0.0,
            "wrong_n": len(sw),
            "wrong_given_skip": len(sw) / len(ss) if ss else 0.0,
            "wrong_over_activated": len(sw) / len(sa) if sa else 0.0,
            "wrong_over_eligible": len(sw) / len(subset) if subset else 0.0,
            "max_regret_norm": max((max(0.0, -s.truth) for s in sw), default=0.0),
            "bound_violation_rate": (sum(s.truth < s.pred - margin for s in subset) / len(subset)) if subset else 0.0,
            "eval_time_median_ns": percentile((s.eval_time for s in sa), 0.50) if sa else 0.0,
            "rdo12_time_median_ns": percentile((s.rdo12 for s in subset), 0.50) if subset else 0.0,
        }
    return {
        "n_all": len(samples),
        "n_eligible": len(eligible),
        "activation_profile": activation_profile,
        "activated_n": len(activated),
        "activation_rate": len(activated) / len(eligible) if eligible else 0.0,
        "skip_n": len(skip),
        "skip_rate": len(skip) / len(activated) if activated else 0.0,
        "conditional_prune_rate": len(skip) / len(activated) if activated else 0.0,
        "prune_rate_over_eligible": len(skip) / len(eligible) if eligible else 0.0,
        "wrong_n": len(wrong),
        "wrong_given_skip": len(wrong) / len(skip) if skip else 0.0,
        "wrong_overall": len(wrong) / len(eligible) if eligible else 0.0,
        "wrong_over_activated": len(wrong) / len(activated) if activated else 0.0,
        "wrong_over_eligible": len(wrong) / len(eligible) if eligible else 0.0,
        "bound_violation_rate": len(violations) / len(eligible) if eligible else 0.0,
        "regret_norm_mean_wrong": sum(regrets) / len(regrets) if regrets else 0.0,
        "regret_norm_p95_wrong": percentile(regrets, 0.95) if regrets else 0.0,
        "regret_norm_p99_wrong": percentile(regrets, 0.99) if regrets else 0.0,
        "regret_norm_max_wrong": max(regrets, default=0.0),
        "pearson_pred_true": pearson(pred, truth),
        "spearman_pred_true": pearson(ranks(pred), ranks(truth)),
        "mae_pred_true": (sum(abs(s.pred - s.truth) for s in eligible) / len(eligible)) if eligible else math.nan,
        "pred_p05": percentile(pred, 0.05),
        "pred_p50": percentile(pred, 0.50),
        "pred_p95": percentile(pred, 0.95),
        "true_p05": percentile(truth, 0.05),
        "true_p50": percentile(truth, 0.50),
        "true_p95": percentile(truth, 0.95),
        "estimated_nonzero_rdo_time_saved_fraction_gross": saved_rdo12 / total_rdo12 if total_rdo12 > 0 else 0.0,
        "estimated_nonzero_rdo_time_saved_fraction_net_after_stage3": net_saved / total_rdo12 if total_rdo12 > 0 else 0.0,
        "estimated_total_lfnst_rdo_time_saved_fraction_gross": saved_rdo12 / total_all_rdo if total_all_rdo > 0 else 0.0,
        "estimated_total_lfnst_rdo_time_saved_fraction_net_after_stage3": net_saved / total_all_rdo if total_all_rdo > 0 else 0.0,
        "stage3_eval_time_total_ns": total_eval,
        "stage3_eval_time_mean_ns": (sum(s.eval_time for s in activated) / len(activated)) if activated else 0.0,
        "stage3_eval_time_trimmed_mean_1pct_ns": eval_trim,
        "nonzero_rdo_time_trimmed_mean_1pct_ns": rdo12_trim,
        "estimated_nonzero_rdo_time_saved_fraction_net_robust_1pct": robust_net_fraction,
        "stage3_eval_time_median_ns": percentile((s.eval_time for s in activated), 0.50) if activated else 0.0,
        "nonzero_rdo_time_median_ns": percentile((s.rdo12 for s in eligible), 0.50) if eligible else 0.0,
        "eval_over_rdo12_time_ratio_total": total_eval / total_rdo12 if total_rdo12 > 0 else 0.0,
        "by_sequence": per_seq,
    }


def qard_additional(mode: int, profile: int, margin: float, *, kappa_h: float, kappa_v: float,
                    rho_h: float, rho_v: float, idx_bits: float, model: int = 3,
                    activation_profile: int = 0, stat_file: str = "") -> str:
    parts = [
        BASE_STAGE12,
        f"LardLfnst21Stage3RdeMode={mode}",
        f"LardLfnst21Stage3RdeProfile={profile}",
        f"LardLfnst21Stage3RdeModel={model}",
        f"LardLfnst21Stage3RdeActivationProfile={activation_profile}",
        f"LardLfnst21Stage3RdeRiskMargin={margin:.17g}",
        f"LardLfnst21Stage3RdeKappaH={kappa_h:.17g}",
        f"LardLfnst21Stage3RdeKappaV={kappa_v:.17g}",
        f"LardLfnst21Stage3RdeRhoBaseH={rho_h:.17g}",
        f"LardLfnst21Stage3RdeRhoBaseV={rho_v:.17g}",
        f"LardLfnst21Stage3RdeIdxBits={idx_bits:.17g}",
    ]
    if stat_file:
        parts.append(f"LardLfnst21Stage3RdeStatFile={stat_file}")
    return " ".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--calibration", action="append", default=[], metavar="SEQ=CSV", help="repeat for sequence-level calibration CSVs")
    ap.add_argument("--test", action="append", default=[], metavar="SEQ=CSV", help="held-out sequence CSVs; optional but strongly recommended")
    ap.add_argument("--alpha", type=float, default=0.005, help="one-sided target tail probability (default 0.005)")
    ap.add_argument("--margin-mode", choices=("sequence_max", "pooled"), default="sequence_max")
    ap.add_argument("--profile", type=int, choices=(0, 1, 2), default=2, help="real eligibility: 0 safe, 1 16-output, 2 all QARD-eligible")
    ap.add_argument("--model", type=int, choices=(2, 3), default=3, help="2 full covariance reference; 3 fast empirical second-moment deployment")
    ap.add_argument("--activation-profile", type=int, choices=(0, 1), default=1,
                    help="Model3 runtime activation: 0 all eligible; 1 free DCT2 AbsSum + fractional-rate-density gate")
    ap.add_argument("--kappa-h", type=float, default=32.0)
    ap.add_argument("--kappa-v", type=float, default=32.0)
    ap.add_argument("--rho-base-h", type=float, default=0.6)
    ap.add_argument("--rho-base-v", type=float, default=0.6)
    ap.add_argument("--idx-bits", type=float, default=1.0)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    if not (0.0 < args.alpha < 0.5):
        raise ValueError("--alpha must be in (0, 0.5)")
    if not args.calibration:
        raise ValueError("at least one --calibration SEQ=CSV is required")

    calibration: list[Sample] = []
    cal_by_seq: dict[str, list[Sample]] = {}
    source_manifest: dict[str, list[str]] = {}
    for spec in args.calibration:
        label, path = parse_spec(spec)
        rows = load_csv(label, path)
        cal_by_seq.setdefault(label, []).extend(rows)
        calibration.extend(rows)
        source_manifest.setdefault(f"calibration:{label}", []).append(str(path.resolve()))
    test: list[Sample] = []
    for spec in args.test:
        label, path = parse_spec(spec)
        rows = load_csv(label, path)
        test.extend(rows)
        source_manifest.setdefault(f"test:{label}", []).append(str(path.resolve()))

    cal_labels = set(cal_by_seq)
    test_labels = {s.sequence for s in test}
    overlap = sorted(cal_labels.intersection(test_labels))
    if overlap:
        raise RuntimeError(f"sequence leakage: labels appear in both calibration and held-out test: {overlap}")

    cal_by_seq_eligible = {
        seq: [s for s in rows if real_eligible(s, args.profile)]
        for seq, rows in cal_by_seq.items()
    }
    empty = [seq for seq, rows in cal_by_seq_eligible.items() if not rows]
    if empty:
        raise RuntimeError(f"no real-eligible calibration samples for profile {args.profile}: {empty}")
    calibration_eligible = [s for rows in cal_by_seq_eligible.values() for s in rows]
    seq_margins = {seq: upper_order_quantile((s.error for s in rows), args.alpha) for seq, rows in cal_by_seq_eligible.items()}
    if args.margin_mode == "sequence_max":
        margin = max(seq_margins.values())
    else:
        margin = upper_order_quantile((s.error for s in calibration_eligible), args.alpha)
    # A negative error quantile means the model is already conservatively low. Risk margin is constrained
    # non-negative in the encoder so that real pruning can never be made more aggressive by calibration.
    margin = max(0.0, margin)

    result = {
        "method": "Skip21 Stage3 covariance-QARD one-sided lower bound",
        "alpha": args.alpha,
        "margin_mode": args.margin_mode,
        "risk_margin": margin,
        "per_sequence_calibration_margin": seq_margins,
        "risk_calibration_activation_applied": False,
        "calibration": evaluate(calibration, margin, args.profile, args.activation_profile),
        "test": evaluate(test, margin, args.profile, args.activation_profile) if test else None,
        "sources": source_manifest,
        "parameters": {
            "profile": args.profile,
            "model": args.model,
            "activation_profile": args.activation_profile,
            "kappa_h": args.kappa_h,
            "kappa_v": args.kappa_v,
            "rho_base_h": args.rho_base_h,
            "rho_base_v": args.rho_base_v,
            "idx_bits": args.idx_bits,
        },
        "decision_rule": "prune {1,2} iff predMinNormQard - risk_margin >= 0",
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_json = args.out_dir / "stage3_qard_calibration.json"
    out_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    real = qard_additional(2, args.profile, margin, kappa_h=args.kappa_h, kappa_v=args.kappa_v,
                           rho_h=args.rho_base_h, rho_v=args.rho_base_v, idx_bits=args.idx_bits,
                           model=args.model, activation_profile=args.activation_profile)
    shadow = qard_additional(1, args.profile, 1e9, kappa_h=args.kappa_h, kappa_v=args.kappa_v,
                             rho_h=args.rho_base_h, rho_v=args.rho_base_v, idx_bits=args.idx_bits,
                             model=args.model, activation_profile=args.activation_profile)
    (args.out_dir / "stage3_qard_real.additional.txt").write_text(real + "\n", encoding="utf-8")
    (args.out_dir / "stage3_qard_shadow.additional.txt").write_text(shadow + "\n", encoding="utf-8")
    profile_json = {"profiles": {"S123_QARD_REAL_CAL": real, "S123_QARD_SHADOW": shadow}}
    (args.out_dir / "stage3_qard_profiles.json").write_text(json.dumps(profile_json, indent=2) + "\n", encoding="utf-8")

    print(f"risk_margin={margin:.17g}")
    print(f"calibration_n_all={len(calibration)}")
    print(f"calibration_n_eligible={len(calibration_eligible)}")
    if test:
        print(f"test_n={len(test)}")
    print(f"json={out_json}")
    print(f"profiles={args.out_dir / 'stage3_qard_profiles.json'}")


if __name__ == "__main__":
    main()
