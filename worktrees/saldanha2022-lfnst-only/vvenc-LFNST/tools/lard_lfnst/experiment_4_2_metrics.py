from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

EPS = 1.0e-12
DEFAULT_THETA_VALUES = [0.0, 30.0, 60.0, 75.0]


@dataclass(frozen=True, order=True)
class GroupKey:
    qp: int
    w: int
    h: int
    lat_bin: int
    set_idx: int
    transpose: int
    k: int


@dataclass(frozen=True)
class VectorSample:
    group_key: GroupKey
    kz: int
    values: np.ndarray
    sigma2_res: float | None = None


@dataclass(frozen=True)
class RdoSample:
    group_key: GroupKey
    j0: float
    j1: float
    j2: float
    best_idx: int
    sigma2_res: float | None

    @property
    def delta_j1(self) -> float:
        return self.j0 - self.j1

    @property
    def delta_j2(self) -> float:
        return self.j0 - self.j2

    @property
    def delta_jmax(self) -> float:
        return self.j0 - min(self.j1, self.j2)


def _value(row: dict[str, object], *names: str, default: object | None = None) -> object | None:
    for name in names:
        if name in row and row[name] != "":
            return row[name]
    return default


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value: object, default: float = math.nan) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def zero_out_retained_count(w: int, h: int) -> int:
    return 8 if (w == 4 and h == 4) or (w == 8 and h == 8) else 16


def lat_bin_from_row(row: dict[str, object], theta_values: list[float]) -> int:
    direct = _value(row, "latBin", "lat_bin", default=None)
    if direct is not None:
        return _to_int(direct)
    bucket = _value(row, "latBucket", default=None)
    if bucket is not None:
        return min(max(_to_int(bucket), 0), len(theta_values) - 1)
    abs_lat = _to_float(_value(row, "absLatDeg", default=0.0), 0.0)
    values = np.asarray(theta_values, dtype=np.float64)
    return int(np.argmin(np.abs(values - abs_lat)))


def canonical_vector_row(row: dict[str, object], theta_values: list[float] | None = None) -> VectorSample:
    theta_values = theta_values or DEFAULT_THETA_VALUES
    w = _to_int(_value(row, "w", "W"))
    h = _to_int(_value(row, "h", "H"))
    qp = _to_int(_value(row, "qp", "QP"))
    lat_bin = lat_bin_from_row(row, theta_values)
    set_idx = _to_int(_value(row, "lfnstSetIdx", "setIdx", "lfnstSet", default=0))
    transpose = _to_int(_value(row, "transposeFlag", "transpose", default=0))
    k = _to_int(_value(row, "trSize", "inputVectorDim", "kIn", default=48))
    values = np.zeros(k, dtype=np.float64)
    for idx in range(k):
        values[idx] = _to_float(_value(row, f"x{idx:02d}", default=0.0), 0.0)
    sigma2_res = _to_float(_value(row, "sigma2_res", default=math.nan))
    return VectorSample(
        group_key=GroupKey(qp=qp, w=w, h=h, lat_bin=lat_bin, set_idx=set_idx, transpose=transpose, k=k),
        kz=zero_out_retained_count(w, h),
        values=np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0),
        sigma2_res=sigma2_res if math.isfinite(sigma2_res) else None,
    )


def canonical_rdo_row(row: dict[str, object]) -> RdoSample | None:
    j0 = _to_float(_value(row, "J0", default=math.nan))
    j1 = _to_float(_value(row, "J1", default=math.nan))
    j2 = _to_float(_value(row, "J2", default=math.nan))
    if not all(math.isfinite(v) and abs(v) < 1.0e300 for v in (j0, j1, j2)):
        return None
    w = _to_int(_value(row, "w", "W"))
    h = _to_int(_value(row, "h", "H"))
    qp = _to_int(_value(row, "qp", "QP"))
    k = _to_int(_value(row, "kIn", "trSize", "inputVectorDim", default=48))
    sigma2_res = _to_float(_value(row, "sigma2_res", default=math.nan))
    return RdoSample(
        group_key=GroupKey(
            qp=qp,
            w=w,
            h=h,
            lat_bin=_to_int(_value(row, "latBin", "lat_bin", default=0)),
            set_idx=_to_int(_value(row, "setIdx", "lfnstSetIdx", "lfnstSet", default=0)),
            transpose=_to_int(_value(row, "transpose", "transposeFlag", default=0)),
            k=k,
        ),
        j0=j0,
        j1=j1,
        j2=j2,
        best_idx=_to_int(_value(row, "bestIdx", default=0)),
        sigma2_res=sigma2_res if math.isfinite(sigma2_res) else None,
    )


class CovAccumulator:
    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.n = 0
        self.sum_x = np.zeros(dim, dtype=np.float64)
        self.sum_xx = np.zeros((dim, dim), dtype=np.float64)
        self.sigma2_values: list[float] = []

    def add(self, values: np.ndarray, sigma2_res: float | None = None) -> None:
        vec = np.asarray(values[: self.dim], dtype=np.float64)
        vec = np.nan_to_num(vec, nan=0.0, posinf=0.0, neginf=0.0)
        self.n += 1
        self.sum_x += vec
        self.sum_xx += np.outer(vec, vec)
        if sigma2_res is not None and math.isfinite(sigma2_res):
            self.sigma2_values.append(float(sigma2_res))

    def add_many(self, values: np.ndarray) -> None:
        vals = np.asarray(values[:, : self.dim], dtype=np.float64)
        vals = np.nan_to_num(vals, nan=0.0, posinf=0.0, neginf=0.0)
        self.n += int(vals.shape[0])
        self.sum_x += vals.sum(axis=0)
        self.sum_xx += vals.T @ vals

    def covariance(self) -> np.ndarray:
        if self.n <= 1:
            return np.zeros((self.dim, self.dim), dtype=np.float64)
        mean = self.sum_x / float(self.n)
        cov = (self.sum_xx - float(self.n) * np.outer(mean, mean)) / float(self.n - 1)
        return (cov + cov.T) * 0.5

    def sigma2_mean(self) -> float:
        return float(np.mean(self.sigma2_values)) if self.sigma2_values else 1.0


def correlation_matrix(sigma: np.ndarray, eps: float = EPS) -> tuple[np.ndarray, np.ndarray]:
    diag = np.asarray(np.diag(sigma), dtype=np.float64)
    active = np.isfinite(diag) & (diag > eps)
    scale = np.sqrt(np.maximum(diag, eps))
    corr = sigma / (scale[:, None] * scale[None, :] + eps)
    corr[~np.isfinite(corr)] = 0.0
    return corr, active


def normalized_covariance_error(r_emp: np.ndarray, r_th: np.ndarray, active: np.ndarray, offdiag_only: bool) -> float:
    idx = np.flatnonzero(active)
    if idx.size == 0:
        return math.nan
    emp = r_emp[np.ix_(idx, idx)]
    th = r_th[np.ix_(idx, idx)]
    if offdiag_only:
        mask = ~np.eye(emp.shape[0], dtype=bool)
        emp_vec = emp[mask]
        th_vec = th[mask]
    else:
        emp_vec = emp.ravel()
        th_vec = th.ravel()
    denom = float(np.linalg.norm(emp_vec)) + EPS
    return float(np.linalg.norm(emp_vec - th_vec) / denom)


def _rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.size, dtype=np.float64)
    sorted_values = values[order]
    start = 0
    while start < values.size:
        end = start + 1
        while end < values.size and sorted_values[end] == sorted_values[start]:
            end += 1
        rank = 0.5 * (start + end - 1) + 1.0
        ranks[order[start:end]] = rank
        start = end
    return ranks


def spearman(x: Iterable[float], y: Iterable[float]) -> float:
    xa = np.asarray(list(x), dtype=np.float64)
    ya = np.asarray(list(y), dtype=np.float64)
    mask = np.isfinite(xa) & np.isfinite(ya)
    xa = xa[mask]
    ya = ya[mask]
    if xa.size < 2:
        return math.nan
    rx = _rankdata(xa)
    ry = _rankdata(ya)
    if np.std(rx) <= EPS or np.std(ry) <= EPS:
        return math.nan
    return float(np.corrcoef(rx, ry)[0, 1])


def upper_offdiag_values(mat: np.ndarray, active: np.ndarray) -> np.ndarray:
    idx = np.flatnonzero(active)
    if idx.size < 2:
        return np.asarray([], dtype=np.float64)
    sub = mat[np.ix_(idx, idx)]
    rows, cols = np.triu_indices(sub.shape[0], k=1)
    return sub[rows, cols].astype(np.float64, copy=False)


def covariance_rank_correlation(r_emp: np.ndarray, r_th: np.ndarray, active: np.ndarray) -> tuple[float, int]:
    emp = upper_offdiag_values(r_emp, active)
    th = upper_offdiag_values(r_th, active)
    rho = spearman(emp, th)
    return rho, int(math.isfinite(rho))


def offdiag_abs_mean_corr_from_corr(r: np.ndarray, active: np.ndarray) -> float:
    vals = upper_offdiag_values(np.abs(r), active)
    return float(np.mean(vals)) if vals.size else math.nan


def diag_dominance(sigma: np.ndarray, active: np.ndarray | None = None) -> float:
    if active is None:
        active = np.ones(sigma.shape[0], dtype=bool)
    idx = np.flatnonzero(active)
    if idx.size == 0:
        return math.nan
    sub = sigma[np.ix_(idx, idx)]
    return float(np.sum(np.abs(np.diag(sub))) / (np.sum(np.abs(sub)) + EPS))


def response_metrics(sigma: np.ndarray, lfnst: np.ndarray) -> dict[str, float]:
    rows = []
    for cand in range(2):
        mat = np.asarray(lfnst[cand], dtype=np.float64)
        cov_y = mat @ sigma @ mat.T
        diag_energy = float(np.trace(cov_y))
        off = cov_y.copy()
        np.fill_diagonal(off, 0.0)
        off_plus = float(np.sum(np.maximum(off, 0.0)))
        rows.append((diag_energy, off_plus))
    return {
        "G1_resp": rows[0][0],
        "G2_resp": rows[1][0],
        "G_max_resp": max(rows[0][0], rows[1][0]),
        "U1_offplus": rows[0][1],
        "U2_offplus": rows[1][1],
        "U_max_offplus": max(rows[0][1], rows[1][1]),
    }


def theory_top1_candidate(metrics: dict[str, float], lambda_u: float = 0.0) -> int:
    s1 = float(metrics["G1_resp"]) + lambda_u * float(metrics["U1_offplus"])
    s2 = float(metrics["G2_resp"]) + lambda_u * float(metrics["U2_offplus"])
    return 1 if s1 >= s2 else 2


def rdo_group_metrics(samples: list[RdoSample]) -> dict[str, float | int]:
    if not samples:
        return {
            "rdo_count": 0,
            "deltaJ1_mean": math.nan,
            "deltaJ2_mean": math.nan,
            "deltaJmax_mean": math.nan,
            "P_positive_gain": math.nan,
            "P_no_gain": math.nan,
            "rdo_top1": 0,
            "top1_rdo_valid": 0,
        }
    d1 = np.asarray([s.delta_j1 for s in samples], dtype=np.float64)
    d2 = np.asarray([s.delta_j2 for s in samples], dtype=np.float64)
    dm = np.asarray([s.delta_jmax for s in samples], dtype=np.float64)
    mean1 = float(np.mean(d1))
    mean2 = float(np.mean(d2))
    max_gain = max(mean1, mean2)
    return {
        "rdo_count": len(samples),
        "deltaJ1_mean": mean1,
        "deltaJ2_mean": mean2,
        "deltaJmax_mean": float(np.mean(dm)),
        "P_positive_gain": float(np.mean(dm > 0.0)),
        "P_no_gain": float(np.mean(dm <= 0.0)),
        "rdo_top1": 1 if mean1 >= mean2 else 2,
        "top1_rdo_valid": int(max_gain > 0.0),
    }


def _row_from_key(key: GroupKey) -> dict[str, int]:
    return {
        "QP": key.qp,
        "W": key.w,
        "H": key.h,
        "latBin": key.lat_bin,
        "setIdx": key.set_idx,
        "transpose": key.transpose,
        "K": key.k,
        "Kz": zero_out_retained_count(key.w, key.h),
    }


def zscore(values: np.ndarray) -> np.ndarray:
    vals = np.asarray(values, dtype=np.float64)
    if vals.size == 0 or not np.isfinite(vals).any():
        return np.zeros_like(vals)
    mu = np.nanmean(vals)
    sd = np.nanstd(vals)
    if not math.isfinite(sd) or sd <= EPS:
        return np.zeros_like(vals)
    return (vals - mu) / sd


def reliability_curve(group_df: pd.DataFrame, bins: int = 6) -> pd.DataFrame:
    columns = ["bin", "groups", "S_low_min", "S_low_max", "P_no_gain"]
    if group_df.empty:
        return pd.DataFrame(columns=columns)
    frame = group_df.copy()
    required = ["O_x_th", "chi_diag_th", "G_max_resp_th", "U_max_offplus_th", "P_no_gain"]
    if any(col not in frame.columns for col in required):
        return pd.DataFrame(columns=columns)
    components = [
        -frame["O_x_th"].to_numpy(dtype=np.float64),
        frame["chi_diag_th"].to_numpy(dtype=np.float64),
        -frame["G_max_resp_th"].to_numpy(dtype=np.float64),
        -frame["U_max_offplus_th"].to_numpy(dtype=np.float64),
    ]
    frame["S_low"] = sum(zscore(v) for v in components)
    frame = frame[np.isfinite(frame["S_low"]) & np.isfinite(frame["P_no_gain"])].copy()
    if frame.empty:
        return pd.DataFrame(columns=columns)
    q = min(max(1, bins), len(frame))
    frame["bin"] = pd.qcut(frame["S_low"].rank(method="first"), q=q, labels=[f"Q{i + 1}" for i in range(q)])
    return (
        frame.groupby("bin", observed=True)
        .agg(groups=("S_low", "size"), S_low_min=("S_low", "min"), S_low_max=("S_low", "max"), P_no_gain=("P_no_gain", "mean"))
        .reset_index()
    )


def plot_formal_outputs(out_dir: Path, cov_df: pd.DataFrame, merged_df: pd.DataFrame, reliability_df: pd.DataFrame) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(7.0, 3.8), constrained_layout=True)
    if not cov_df.empty:
        frame = cov_df.copy()
        frame["sizeId"] = frame["W"].astype(str) + "x" + frame["H"].astype(str)
        labels = []
        values = []
        for (size, lat), group in frame.groupby(["sizeId", "latBin"], sort=True):
            labels.append(f"{size}/L{lat}")
            values.append(float(group["NCE_off"].median()))
        ax.bar(np.arange(len(values)), values)
        ax.set_xticks(np.arange(len(labels)))
        ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
    ax.set_ylabel("median NCE-off")
    ax.set_title("Experiment 4.2 covariance error")
    fig.savefig(out_dir / "fig_4_2_nce_by_size_lat.png", dpi=220)
    fig.savefig(out_dir / "fig_4_2_nce_by_size_lat.pdf")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(5.2, 3.8), constrained_layout=True)
    if not merged_df.empty:
        ax.scatter(merged_df["G_max_resp_th"], merged_df["P_positive_gain"], s=22, alpha=0.75, label="G")
        ax.set_xlabel("theoretical G_max_resp")
        ax.set_ylabel("P(DeltaJmax > 0)")
    ax.grid(True, alpha=0.3)
    ax.set_title("Theory response vs real gain")
    fig.savefig(out_dir / "fig_4_2_response_vs_gain.png", dpi=220)
    fig.savefig(out_dir / "fig_4_2_response_vs_gain.pdf")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(5.2, 3.6), constrained_layout=True)
    if not reliability_df.empty:
        ax.plot(np.arange(len(reliability_df)), reliability_df["P_no_gain"], marker="o")
        ax.set_xticks(np.arange(len(reliability_df)))
        ax.set_xticklabels(reliability_df["bin"].astype(str))
    ax.set_xlabel("S_low quantile")
    ax.set_ylabel("P(DeltaJmax <= 0)")
    ax.grid(True, alpha=0.3)
    ax.set_title("Low-gain reliability")
    fig.savefig(out_dir / "fig_4_2_low_gain_reliability.png", dpi=220)
    fig.savefig(out_dir / "fig_4_2_low_gain_reliability.pdf")
    plt.close(fig)


def write_formal_analysis_outputs(
    out_dir: Path,
    empirical_accs: dict[GroupKey, CovAccumulator],
    theory_cov_by_key: dict[GroupKey, np.ndarray],
    lfnst_by_key: dict[GroupKey, np.ndarray],
    rdo_by_key: dict[GroupKey, list[RdoSample]],
    min_samples: int,
    lambda_u: float = 0.0,
) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cov_rows: list[dict[str, float | int]] = []
    resp_rows: list[dict[str, float | int]] = []
    rdo_rows: list[dict[str, float | int]] = []
    top_rows: list[dict[str, float | int]] = []
    matrices: dict[str, np.ndarray] = {}

    for key, acc in sorted(empirical_accs.items()):
        row_base = _row_from_key(key)
        coverage = {**row_base, "samples": acc.n, "admitted": int(acc.n >= min_samples)}
        if acc.n < min_samples or key not in theory_cov_by_key:
            cov_rows.append({**coverage, "NCE_full": math.nan, "NCE_off": math.nan, "rho_rank_cov": math.nan, "rank_valid": 0})
            continue

        sigma_emp = acc.covariance()
        sigma_th = np.asarray(theory_cov_by_key[key], dtype=np.float64)[: key.k, : key.k]
        r_emp, active_emp = correlation_matrix(sigma_emp)
        r_th, active_th = correlation_matrix(sigma_th)
        active = active_emp & active_th
        rho_rank, rank_valid = covariance_rank_correlation(r_emp, r_th, active)
        cov_rows.append(
            {
                **coverage,
                "NCE_full": normalized_covariance_error(r_emp, r_th, active, offdiag_only=False),
                "NCE_off": normalized_covariance_error(r_emp, r_th, active, offdiag_only=True),
                "rho_rank_cov": rho_rank,
                "rank_valid": rank_valid,
                "O_x_emp": offdiag_abs_mean_corr_from_corr(r_emp, active),
                "O_x_th": offdiag_abs_mean_corr_from_corr(r_th, active),
                "chi_diag_emp": diag_dominance(sigma_emp, active),
                "chi_diag_th": diag_dominance(sigma_th, active),
            }
        )
        matrices[f"emp_qp{key.qp}_{key.w}x{key.h}_lat{key.lat_bin}_set{key.set_idx}_tr{key.transpose}_k{key.k}"] = sigma_emp.astype(np.float32)
        matrices[f"th_qp{key.qp}_{key.w}x{key.h}_lat{key.lat_bin}_set{key.set_idx}_tr{key.transpose}_k{key.k}"] = sigma_th.astype(np.float32)

        if key in lfnst_by_key:
            emp_resp = response_metrics(sigma_emp, lfnst_by_key[key])
            th_resp = response_metrics(sigma_th, lfnst_by_key[key])
            resp_row = {
                **row_base,
                "G1_resp_emp": emp_resp["G1_resp"],
                "G2_resp_emp": emp_resp["G2_resp"],
                "G_max_resp_emp": emp_resp["G_max_resp"],
                "U1_offplus_emp": emp_resp["U1_offplus"],
                "U2_offplus_emp": emp_resp["U2_offplus"],
                "U_max_offplus_emp": emp_resp["U_max_offplus"],
                "G1_resp_th": th_resp["G1_resp"],
                "G2_resp_th": th_resp["G2_resp"],
                "G_max_resp_th": th_resp["G_max_resp"],
                "U1_offplus_th": th_resp["U1_offplus"],
                "U2_offplus_th": th_resp["U2_offplus"],
                "U_max_offplus_th": th_resp["U_max_offplus"],
                "theory_top1": theory_top1_candidate(th_resp, lambda_u=lambda_u),
            }
            resp_rows.append(resp_row)
            rdo = rdo_group_metrics(rdo_by_key.get(key, []))
            rdo_rows.append({**row_base, **rdo})
            if int(rdo["top1_rdo_valid"]):
                top_rows.append(
                    {
                        **row_base,
                        "theory_top1": resp_row["theory_top1"],
                        "rdo_top1": rdo["rdo_top1"],
                        "match": int(resp_row["theory_top1"] == rdo["rdo_top1"]),
                        "deltaJ1_mean": rdo["deltaJ1_mean"],
                        "deltaJ2_mean": rdo["deltaJ2_mean"],
                    }
                )

    cov_df = pd.DataFrame(cov_rows)
    resp_df = pd.DataFrame(resp_rows)
    rdo_df = pd.DataFrame(rdo_rows)
    top_df = pd.DataFrame(top_rows)
    cov_df.to_csv(out_dir / "covariance_group_metrics.csv", index=False)
    resp_df.to_csv(out_dir / "response_group_metrics.csv", index=False)
    rdo_df.to_csv(out_dir / "rdo_gain_group_metrics.csv", index=False)
    top_df.to_csv(out_dir / "top1_candidate_match.csv", index=False)
    if matrices:
        np.savez_compressed(out_dir / "empirical_theory_covariance_matrices.npz", **matrices)

    merge_keys = ["QP", "W", "H", "latBin", "setIdx", "transpose", "K", "Kz"]
    merged = cov_df.merge(resp_df, on=merge_keys, how="inner") if not cov_df.empty and not resp_df.empty else pd.DataFrame()
    merged = merged.merge(rdo_df, on=merge_keys, how="inner") if not merged.empty and not rdo_df.empty else pd.DataFrame()
    rank_rows = [
        {"metric": "O_x", "spearman_emp_th": spearman(merged["O_x_th"], merged["O_x_emp"]) if not merged.empty else math.nan},
        {"metric": "chi_diag", "spearman_emp_th": spearman(merged["chi_diag_th"], merged["chi_diag_emp"]) if not merged.empty else math.nan},
        {"metric": "G_max_resp", "spearman_emp_th": spearman(merged["G_max_resp_th"], merged["G_max_resp_emp"]) if not merged.empty else math.nan},
        {"metric": "U_max_offplus", "spearman_emp_th": spearman(merged["U_max_offplus_th"], merged["U_max_offplus_emp"]) if not merged.empty else math.nan},
        {"metric": "G_vs_P_positive", "spearman_emp_th": spearman(merged["G_max_resp_th"], merged["P_positive_gain"]) if not merged.empty else math.nan},
        {"metric": "U_vs_P_positive", "spearman_emp_th": spearman(merged["U_max_offplus_th"], merged["P_positive_gain"]) if not merged.empty else math.nan},
        {"metric": "O_vs_P_positive", "spearman_emp_th": spearman(merged["O_x_th"], merged["P_positive_gain"]) if not merged.empty else math.nan},
        {"metric": "chi_vs_P_positive", "spearman_emp_th": spearman(merged["chi_diag_th"], merged["P_positive_gain"]) if not merged.empty else math.nan},
    ]
    pd.DataFrame(rank_rows).to_csv(out_dir / "metric_rank_correlations.csv", index=False)
    reliability = reliability_curve(merged)
    reliability.to_csv(out_dir / "low_gain_reliability_curve.csv", index=False)
    plot_formal_outputs(out_dir, cov_df, merged, reliability)
    pd.DataFrame(
        [
            {
                "groups": int(len(cov_df)),
                "admitted_groups": int(cov_df["admitted"].sum()) if "admitted" in cov_df else 0,
                "top1_groups": int(len(top_df)),
                "Top1Match": float(top_df["match"].mean()) if not top_df.empty else math.nan,
                "median_NCE_full": float(cov_df["NCE_full"].median()) if "NCE_full" in cov_df else math.nan,
                "median_NCE_off": float(cov_df["NCE_off"].median()) if "NCE_off" in cov_df else math.nan,
            }
        ]
    ).to_csv(out_dir / "covariance_validation_summary.csv", index=False)
    return {"groups": int(len(cov_df)), "top1_groups": int(len(top_df))}
