#!/usr/bin/env python3
"""LFNST ablation logging-platform, A1, and B1 experiment helpers."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np


LAT_BUCKETS = [(0.0, 30.0, "[0,30)"), (30.0, 60.0, "[30,60)"), (60.0, 75.0, "[60,75)"), (75.0, 90.0001, "[75,90]")]
EPS = 1.0e-12


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = fieldnames or (list(rows[0].keys()) if rows else [])
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)


def ff(row: dict[str, str], key: str, default: float = math.nan) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def ii(row: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(row.get(key, default)))
    except (TypeError, ValueError):
        return default


def valid_cost(x: float) -> bool:
    return math.isfinite(x) and abs(x) < 1.0e100


def lat_bucket(abs_lat: float) -> str:
    for lo, hi, name in LAT_BUCKETS:
        if lo <= abs_lat < hi:
            return name
    return "unknown"


def mode_group(mode: int) -> str:
    if mode == 0:
        return "planar"
    if mode == 1:
        return "dc"
    if 2 <= mode <= 18:
        return "angular_low"
    if 19 <= mode <= 50:
        return "angular_mid"
    return "angular_high"


def area_group(w: int, h: int) -> str:
    a = w * h
    if a <= 16:
        return "area_16"
    if a <= 32:
        return "area_32"
    if a <= 64:
        return "area_64"
    if a <= 256:
        return "area_256"
    if a <= 1024:
        return "area_1024"
    return "area_large"


def lfnst_size_for_wh(w: int, h: int) -> int:
    return 8 if w >= 8 and h >= 8 else 4


def best_by_lfnst(rows: list[dict[str, str]]) -> dict[int, dict[str, float | int]]:
    best: dict[int, dict[str, float | int]] = {}
    for row in rows:
        idx = ii(row, "lfnstIdx")
        cost = ff(row, "cost")
        if not valid_cost(cost):
            continue
        if idx not in best or cost < float(best[idx]["J"]):
            best[idx] = {
                "J": cost,
                "R": ff(row, "fracBits"),
                "D": ff(row, "dist"),
                "N": ii(row, "nonZero", ii(row, "numSig", -1)),
                "L": ii(row, "lastPos", -1),
                "M": ff(row, "absSum"),
                "mtsIdx": ii(row, "mtsIdx"),
            }
    return best


def trace_block_key(row: dict[str, str]) -> tuple[int, int, int, int, int, int, int]:
    return (ii(row, "poc"), ii(row, "x"), ii(row, "y"), ii(row, "w"), ii(row, "h"), ii(row, "qp"), ii(row, "intraMode"))


def summarize_trace_block(rows: list[dict[str, str]], seq: str) -> dict[str, object]:
    first = rows[0]
    w, h = ii(first, "w"), ii(first, "h")
    mode = ii(first, "intraMode")
    best = best_by_lfnst(rows)
    vals: dict[str, float | int] = {}
    for idx in [0, 1, 2]:
        b = best.get(idx)
        vals[f"J{idx}"] = float(b["J"]) if b else math.nan
        vals[f"R{idx}"] = float(b["R"]) if b else math.nan
        vals[f"D{idx}"] = float(b["D"]) if b else math.nan
        vals[f"N{idx}"] = int(b["N"]) if b else -1
        vals[f"L{idx}"] = int(b["L"]) if b else -1
        vals[f"M{idx}"] = float(b["M"]) if b else math.nan
    j0, j1, j2 = float(vals["J0"]), float(vals["J1"]), float(vals["J2"])
    candidates = [(0, j0), (1, j1), (2, j2)]
    valid = [(idx, cost) for idx, cost in candidates if valid_cost(cost)]
    lstar = min(valid, key=lambda x: x[1])[0] if valid else -1
    best_lfnst = min(j1 if valid_cost(j1) else math.inf, j2 if valid_cost(j2) else math.inf)
    has_lfnst = valid_cost(best_lfnst)
    n0 = int(vals["N0"])
    n1 = int(vals["N1"])
    n2 = int(vals["N2"])
    l0 = int(vals["L0"])
    l1 = int(vals["L1"])
    l2 = int(vals["L2"])
    m0 = float(vals["M0"])
    m1 = float(vals["M1"])
    m2 = float(vals["M2"])
    abs_lat = ff(first, "absLatDeg")
    row = {
        "seq": seq,
        "POC": ii(first, "poc"),
        "QP": ii(first, "qp"),
        "x": ii(first, "x"),
        "y": ii(first, "y"),
        "W": w,
        "H": h,
        "phi": abs_lat,
        "b_phi": lat_bucket(abs_lat),
        "intraMode": mode,
        "modeGroup": mode_group(mode),
        "mtsIdx": int(best.get(0, {}).get("mtsIdx", -1)) if best else -1,
        "lfnstSet": math.nan,
        "lfnstSize": lfnst_size_for_wh(w, h),
        "areaGroup": area_group(w, h),
        "sigma_r2": ff(first, "roiEnergyQ"),
        "C_proxy": ff(first, "corrProxy"),
        "C_off": math.nan,
        "rho_eig": math.nan,
        "H0": math.nan,
        "H1": math.nan,
        "H2": math.nan,
        "G1_raw": math.nan,
        "G2_raw": math.nan,
        "G1_safe": math.nan,
        "G2_safe": math.nan,
        **vals,
        "DeltaJ1": j0 - j1 if valid_cost(j0) and valid_cost(j1) else math.nan,
        "DeltaJ2": j0 - j2 if valid_cost(j0) and valid_cost(j2) else math.nan,
        "DeltaJ_LFNST": j0 - best_lfnst if valid_cost(j0) and has_lfnst else math.nan,
        "DeltaN": n0 - min(n1 if n1 >= 0 else 1 << 30, n2 if n2 >= 0 else 1 << 30) if has_lfnst and n0 >= 0 else math.nan,
        "DeltaL": l0 - min(l1 if l1 >= 0 else 1 << 30, l2 if l2 >= 0 else 1 << 30) if has_lfnst and l0 >= 0 else math.nan,
        "DeltaM": m0 - min(m1 if math.isfinite(m1) else math.inf, m2 if math.isfinite(m2) else math.inf) if has_lfnst and math.isfinite(m0) else math.nan,
        "lStar": lstar,
        "lfnstRdoTested": bool(has_lfnst),
        "wastedRdo": bool(has_lfnst and lstar == 0),
        "positiveGain": bool(has_lfnst and valid_cost(j0) and j0 > best_lfnst),
    }
    return row


def build_labels(args: argparse.Namespace) -> None:
    trace_paths = [Path(p) for p in args.traces]
    out_rows: list[dict[str, object]] = []
    for path in trace_paths:
        seq = args.seq or path.parent.name
        current_key = None
        rows: list[dict[str, str]] = []
        with path.open(newline="", encoding="utf-8", errors="replace") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                key = trace_block_key(row)
                if current_key is None:
                    current_key = key
                if key != current_key:
                    out_rows.append(summarize_trace_block(rows, seq))
                    rows = []
                    current_key = key
                rows.append(row)
            if rows:
                out_rows.append(summarize_trace_block(rows, seq))
    write_csv(Path(args.out_csv), out_rows)
    summary = {
        "traces": [str(p) for p in trace_paths],
        "rows": len(out_rows),
        "lfnstRdoTested": sum(1 for r in out_rows if r["lfnstRdoTested"]),
        "positiveGain": sum(1 for r in out_rows if r["positiveGain"]),
        "wastedRdo": sum(1 for r in out_rows if r["wastedRdo"]),
    }
    Path(args.summary_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.summary_json).write_text(json.dumps(summary, indent=2), encoding="utf-8")


def make_a1_b1_report(args: argparse.Namespace) -> None:
    import matplotlib.pyplot as plt

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    input_rows = read_csv(Path(args.input_summary))
    cand_rows = read_csv(Path(args.candidate_summary))
    npz = np.load(args.npz)
    phis = [0, 15, 30, 45, 60, 75, 85]
    sizes = [4, 8, 16, 32, 64]

    # A1 tables.
    a1_rows = []
    for r in input_rows:
        phi = float(r["phi_abs_deg"])
        if int(round(phi)) not in phis:
            continue
        a1_rows.append(
            {
                "phi_abs_deg": int(round(phi)),
                "W": int(float(r["W"])),
                "H": int(float(r["H"])),
                "transpose": int(float(r["transpose"])),
                "lfnstSize": int(float(r["s"])),
                "K": int(float(r["K"])),
                "C_off": float(r["C_off"]),
                "rho_eig": float(r["rho_eig"]),
                "H0": float(r["H0"]),
                "E_off": float(r["E_off"]),
                "r_eff": float(r["r_eff"]),
                "trace_x": float(r["trace_x"]),
            }
        )
    write_csv(out / "table_a1_covariance_stats_by_phi_size.csv", a1_rows)

    delta_rows = []
    by_key = {(r["W"], r["H"], r["transpose"]): r for r in a1_rows if r["phi_abs_deg"] == 0}
    for r in a1_rows:
        if r["phi_abs_deg"] not in {75, 85}:
            continue
        b = by_key.get((r["W"], r["H"], r["transpose"]))
        if not b:
            continue
        delta_rows.append(
            {
                "phi_abs_deg": r["phi_abs_deg"],
                "W": r["W"],
                "H": r["H"],
                "transpose": r["transpose"],
                "delta_C_off": r["C_off"] - b["C_off"],
                "delta_rho_eig": r["rho_eig"] - b["rho_eig"],
                "delta_H0": r["H0"] - b["H0"],
            }
        )
    write_csv(out / "table_a1_delta_low_high_latitude.csv", delta_rows)

    fig_dir = out / "figures"
    fig_dir.mkdir(exist_ok=True)
    square = [r for r in a1_rows if r["W"] == r["H"] and r["transpose"] == 0]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    for ax, metric in zip(axes, ["C_off", "rho_eig", "H0"]):
        for size in sizes:
            rows = sorted([r for r in square if r["W"] == size], key=lambda x: x["phi_abs_deg"])
            if rows:
                ax.plot([r["phi_abs_deg"] for r in rows], [r[metric] for r in rows], marker="o", label=f"{size}x{size}")
        ax.set_xlabel("|phi| (deg)")
        ax.set_ylabel(metric)
        ax.grid(True, alpha=0.25)
    axes[0].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(fig_dir / "fig_a1_Coff_rhoeig_H0_by_phi_size.png", dpi=220)
    plt.close(fig)

    fig, axes = plt.subplots(1, 4, figsize=(12, 3))
    for ax, phi in zip(axes, [0, 30, 60, 75]):
        key = f"Sigma_x_phi{phi:02d}_W16_H16_s8_tr0"
        mat = np.asarray(npz[key], dtype=np.float64)
        im = ax.imshow(mat, cmap="viridis")
        ax.set_title(f"|phi|={phi} deg")
        ax.set_xticks([])
        ax.set_yticks([])
    fig.colorbar(im, ax=axes.ravel().tolist(), shrink=0.75)
    fig.savefig(fig_dir / "fig_a1_sigma_heatmaps_phi_0_30_60_75.png", dpi=220, bbox_inches="tight")
    plt.close(fig)

    # B1 tables.
    b1_rows = []
    for r in cand_rows:
        phi = int(round(float(r["phi_abs_deg"])))
        if phi not in phis:
            continue
        b1_rows.append(
            {
                "phi_abs_deg": phi,
                "W": int(float(r["W"])),
                "H": int(float(r["H"])),
                "transpose": int(float(r["transpose"])),
                "lfnstSet": int(float(r["t"])),
                "candidate": int(float(r["l"])),
                "H_l": float(r["H_l"]),
                "G_l_ent": float(r["G_ent"]),
                "top4_vl": float(r["top4_vl"]),
                "top8_vl": float(r["top8_vl"]),
                "trace_y": float(r["trace_y"]),
            }
        )
    write_csv(out / "table_b1_candidate_response_by_phi_size_set.csv", b1_rows)

    pref_rows = []
    groups: dict[tuple[int, int, int, int, int], dict[int, float]] = {}
    for r in b1_rows:
        key = (r["phi_abs_deg"], r["W"], r["H"], r["transpose"], r["lfnstSet"])
        groups.setdefault(key, {})[r["candidate"]] = r["G_l_ent"]
    for key, g in groups.items():
        if 1 in g and 2 in g:
            pref_rows.append(
                {
                    "phi_abs_deg": key[0],
                    "W": key[1],
                    "H": key[2],
                    "transpose": key[3],
                    "lfnstSet": key[4],
                    "G1_ent": g[1],
                    "G2_ent": g[2],
                    "candidate_preference": 1 if g[1] >= g[2] else 2,
                    "G_margin_abs": abs(g[1] - g[2]),
                }
            )
    write_csv(out / "table_b1_candidate_preference_by_phi_size_set.csv", pref_rows)

    # B1 figures use square sizes, transpose=0, set=0 for readability.
    sq_b1 = [r for r in b1_rows if r["W"] == r["H"] and r["transpose"] == 0 and r["lfnstSet"] == 0]
    fig, ax = plt.subplots(figsize=(7, 4.4))
    for cand in [1, 2]:
        rows = sorted([r for r in sq_b1 if r["W"] == 16 and r["candidate"] == cand], key=lambda x: x["phi_abs_deg"])
        ax.plot([r["phi_abs_deg"] for r in rows], [r["G_l_ent"] for r in rows], marker="o", label=f"candidate {cand}, 16x16")
    ax.set_xlabel("|phi| (deg)")
    ax.set_ylabel("G_l_ent = H0 - H_l")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(fig_dir / "fig_b1_Gent_vs_phi_candidate_1_2.png", dpi=220)
    plt.close(fig)

    for cand, name in [(1, "fig_b1_Gent_heatmap_latitude_size_l1.png"), (2, "fig_b1_Gent_heatmap_latitude_size_l2.png")]:
        mat = np.full((len(sizes), len(phis)), np.nan)
        for i, size in enumerate(sizes):
            for j, phi in enumerate(phis):
                vals = [r["G_l_ent"] for r in sq_b1 if r["W"] == size and r["phi_abs_deg"] == phi and r["candidate"] == cand]
                if vals:
                    mat[i, j] = float(np.mean(vals))
        fig, ax = plt.subplots(figsize=(7, 4.2))
        im = ax.imshow(mat, aspect="auto", cmap="coolwarm")
        ax.set_xticks(range(len(phis)))
        ax.set_xticklabels([str(p) for p in phis])
        ax.set_yticks(range(len(sizes)))
        ax.set_yticklabels([f"{s}x{s}" for s in sizes])
        ax.set_xlabel("|phi| (deg)")
        ax.set_ylabel("block size")
        fig.colorbar(im, ax=ax, label="G_l_ent")
        fig.tight_layout()
        fig.savefig(fig_dir / name, dpi=220)
        plt.close(fig)

    pref_sq = [r for r in pref_rows if r["W"] == r["H"] and r["transpose"] == 0 and r["lfnstSet"] == 0]
    pref_mat = np.full((len(sizes), len(phis)), np.nan)
    for i, size in enumerate(sizes):
        for j, phi in enumerate(phis):
            vals = [r["candidate_preference"] for r in pref_sq if r["W"] == size and r["phi_abs_deg"] == phi]
            if vals:
                pref_mat[i, j] = vals[0]
    fig, ax = plt.subplots(figsize=(7, 4.2))
    im = ax.imshow(pref_mat, aspect="auto", cmap="Accent", vmin=1, vmax=2)
    ax.set_xticks(range(len(phis)))
    ax.set_xticklabels([str(p) for p in phis])
    ax.set_yticks(range(len(sizes)))
    ax.set_yticklabels([f"{s}x{s}" for s in sizes])
    ax.set_xlabel("|phi| (deg)")
    ax.set_ylabel("block size")
    fig.colorbar(im, ax=ax, ticks=[1, 2], label="preferred candidate")
    fig.tight_layout()
    fig.savefig(fig_dir / "fig_b1_candidate_preference_heatmap.png", dpi=220)
    plt.close(fig)

    # Candidate variance distribution for one representative setting.
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for cand in [1, 2]:
        key = f"vl_phi75_W16_H16_s8_tr0_t0_l{cand}"
        vals = np.asarray(npz[key], dtype=np.float64)
        ax.plot(np.arange(vals.size), vals / (np.sum(vals) + EPS), marker="o", label=f"candidate {cand}")
    ax.set_xlabel("output coefficient index")
    ax.set_ylabel("normalized variance")
    ax.set_title("|phi|=75 deg, 16x16, set 0")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(fig_dir / "fig_b1_candidate_variance_distribution.png", dpi=220)
    plt.close(fig)

    report = {
        "a1_rows": len(a1_rows),
        "b1_rows": len(b1_rows),
        "figures": sorted(p.name for p in fig_dir.glob("*.png")),
    }
    (out / "ablation_theory_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    lab = sub.add_parser("build-labels")
    lab.add_argument("--traces", nargs="+", required=True)
    lab.add_argument("--seq", default="")
    lab.add_argument("--out-csv", required=True)
    lab.add_argument("--summary-json", required=True)

    rep = sub.add_parser("theory-report")
    rep.add_argument("--input-summary", required=True)
    rep.add_argument("--candidate-summary", required=True)
    rep.add_argument("--npz", required=True)
    rep.add_argument("--out-dir", required=True)
    return p


def main() -> None:
    args = build_parser().parse_args()
    if args.cmd == "build-labels":
        build_labels(args)
    elif args.cmd == "theory-report":
        make_a1_b1_report(args)


if __name__ == "__main__":
    main()
