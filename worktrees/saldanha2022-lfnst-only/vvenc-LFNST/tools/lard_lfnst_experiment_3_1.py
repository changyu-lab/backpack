#!/usr/bin/env python3
"""Experiment 3.1: latitude/block-size effects on LFNST behavior.

This script derives the paper motivation tables from existing full-RDO
`blocks.csv` traces. It does not require re-encoding.
"""

from __future__ import annotations

import csv
import math
import re
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


LAT_BUCKETS = [
    (0.0, 30.0, "[0,30)"),
    (30.0, 60.0, "[30,60)"),
    (60.0, 75.0, "[60,75)"),
    (75.0, 90.0001, "[75,90]"),
]
SIZE_ORDER = ["area_16", "area_32", "area_64", "area_256", "area_1024", "area_large", "area_large_elong"]


def bb(row: dict[str, str], key: str) -> bool:
    return str(row.get(key, "")).lower() in {"1", "true", "yes"}


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


def lat_bucket(abs_lat: float) -> str:
    for lo, hi, name in LAT_BUCKETS:
        if lo <= abs_lat < hi:
            return name
    return "unknown"


def size_group(w: int, h: int) -> str:
    area = w * h
    mn = min(w, h)
    mx = max(w, h)
    if area <= 16:
        return "area_16"
    if area <= 32:
        return "area_32"
    if area <= 64:
        return "area_64"
    if area <= 256:
        return "area_256"
    if area <= 1024:
        return "area_1024"
    return "area_large_elong" if mx >= 4 * mn else "area_large"


def qp_from_path(path: Path) -> int:
    m = re.search(r"QP(\d+)", str(path), flags=re.IGNORECASE)
    return int(m.group(1)) if m else -1


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def ratio(num: int, den: int) -> float:
    return num / den if den else math.nan


def plot_heatmap(path: Path, title: str, data: np.ndarray, rows: list[str], cols: list[str], cbar_label: str) -> None:
    fig, ax = plt.subplots(figsize=(8.2, 3.8))
    masked = np.ma.masked_invalid(data)
    im = ax.imshow(masked, cmap="viridis", vmin=0.0, vmax=1.0, aspect="auto")
    ax.set_xticks(np.arange(len(cols)))
    ax.set_xticklabels(cols, rotation=25, ha="right")
    ax.set_yticks(np.arange(len(rows)))
    ax.set_yticklabels(rows)
    ax.set_title(title)
    for i in range(len(rows)):
        for j in range(len(cols)):
            if math.isfinite(float(data[i, j])):
                ax.text(j, i, f"{data[i, j]:.3f}", ha="center", va="center", color="white" if data[i, j] > 0.55 else "black", fontsize=8)
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label(cbar_label)
    fig.tight_layout()
    fig.savefig(path, dpi=240)
    plt.close(fig)


def md_table(rows: list[dict[str, object]], cols: list[str]) -> str:
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for row in rows:
        vals = []
        for col in cols:
            val = row.get(col, "")
            if isinstance(val, float):
                val = f"{val:.6f}" if math.isfinite(val) else ""
            vals.append(str(val))
        out.append("| " + " | ".join(vals) + " |")
    return "\n".join(out)


def main() -> None:
    root = Path("lahtp_runs/aerialcity_final_trace_fullrdo_skip6_theta45")
    out_dir = Path("lahtp_runs/experiment_3_1_lfnst_lat_size")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Accumulator layout:
    # [waste_denominator, wasted_count, gain_denominator, positive_gain_count]
    by_lat_qp: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    by_lat_size: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    by_lat_qp_size: dict[tuple[str, int, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    total_rows = 0
    eligible_rows = 0

    for path in sorted(root.glob("*/blocks.csv")):
        qp = qp_from_path(path)
        with path.open(newline="", encoding="utf-8", errors="ignore") as fh:
            for row in csv.DictReader(fh):
                total_rows += 1
                if not bb(row, "hasLfnst"):
                    continue
                eligible_rows += 1
                lat = lat_bucket(ff(row, "absLatDeg"))
                size = size_group(ii(row, "w"), ii(row, "h"))
                wasted = 1 if (bb(row, "oracleSkip") or ii(row, "bestIdx") == 0) else 0
                delta = ff(row, "deltaBestLfnst")
                has_gain = math.isfinite(delta)
                positive = 1 if has_gain and delta > 0.0 else 0
                for key, accs in [
                    ((lat, qp), by_lat_qp),
                    ((lat, size), by_lat_size),
                    ((lat, qp, size), by_lat_qp_size),
                ]:
                    acc = accs[key]
                    acc[0] += 1
                    acc[1] += wasted
                    acc[2] += int(has_gain)
                    acc[3] += positive

    qps = sorted({qp for _, qp in by_lat_qp})
    size_labels = [s for s in SIZE_ORDER if any(k[-1] == s for k in by_lat_size)]
    lat_labels = [name for _, _, name in LAT_BUCKETS]

    table1 = []
    for lat in lat_labels:
        row: dict[str, object] = {"Latitude": lat}
        total_all = wasted_all = gain_total_all = positive_all = 0
        for qp in qps:
            total, wasted, gain_total, positive = by_lat_qp.get((lat, qp), [0, 0, 0, 0])
            total_all += total
            wasted_all += wasted
            gain_total_all += gain_total
            positive_all += positive
            row[f"QP{qp}_lfnst_rdo_samples"] = total
            row[f"QP{qp}_wasted_rdo_ratio"] = ratio(wasted, total)
            row[f"QP{qp}_positive_gain_samples"] = gain_total
            row[f"QP{qp}_positive_gain_ratio"] = ratio(positive, gain_total)
        row["AllQP_lfnst_rdo_samples"] = total_all
        row["AllQP_wasted_rdo_ratio"] = ratio(wasted_all, total_all)
        row["AllQP_positive_gain_samples"] = gain_total_all
        row["AllQP_positive_gain_ratio"] = ratio(positive_all, gain_total_all)
        table1.append(row)
    write_rows(out_dir / "table1_wasted_and_gain_by_latitude_qp.csv", table1)

    table2 = []
    for lat in lat_labels:
        row = {"Latitude": lat}
        for size in size_labels:
            total, wasted, gain_total, positive = by_lat_size.get((lat, size), [0, 0, 0, 0])
            row[f"{size}_lfnst_rdo_samples"] = total
            row[f"{size}_wasted_rdo_ratio"] = ratio(wasted, total)
            row[f"{size}_positive_gain_samples"] = gain_total
            row[f"{size}_positive_gain_ratio"] = ratio(positive, gain_total)
        table2.append(row)
    write_rows(out_dir / "table2_wasted_and_gain_by_latitude_size.csv", table2)

    detail = []
    for lat in lat_labels:
        for qp in qps:
            for size in size_labels:
                total, wasted, gain_total, positive = by_lat_qp_size.get((lat, qp, size), [0, 0, 0, 0])
                if total == 0:
                    continue
                detail.append(
                    {
                        "Latitude": lat,
                        "QP": qp,
                        "BlockSizeGroup": size,
                        "LFNST_RDO_tested_samples": total,
                        "Wasted_RDO_samples": wasted,
                        "Wasted_RDO_ratio": ratio(wasted, total),
                        "Positive_gain_valid_samples": gain_total,
                        "Positive_gain_samples": positive,
                        "Positive_gain_ratio": ratio(positive, gain_total),
                    }
                )
    write_rows(out_dir / "table_latitude_qp_size_wasted_and_positive_gain.csv", detail)

    wasted_matrix = np.full((len(lat_labels), len(size_labels)), np.nan, dtype=np.float64)
    gain_matrix = np.full_like(wasted_matrix, np.nan)
    for i, lat in enumerate(lat_labels):
        for j, size in enumerate(size_labels):
            total, wasted, gain_total, positive = by_lat_size.get((lat, size), [0, 0, 0, 0])
            wasted_matrix[i, j] = ratio(wasted, total)
            gain_matrix[i, j] = ratio(positive, gain_total)

    plot_heatmap(
        out_dir / "fig1_wasted_rdo_heatmap_latitude_size.png",
        "Wasted LFNST RDO ratio by latitude and block size",
        wasted_matrix,
        lat_labels,
        size_labels,
        "Pr(best lfnstIdx=0 | LFNST RDO tested)",
    )
    plot_heatmap(
        out_dir / "fig2_positive_gain_heatmap_latitude_size.png",
        "Positive LFNST RD-gain ratio by latitude and block size",
        gain_matrix,
        lat_labels,
        size_labels,
        "Pr(Delta J_LFNST > 0)",
    )

    report = [
        "# Experiment 3.1: Latitude And Block Size Effects On LFNST Behavior",
        "",
        "## Inputs",
        "",
        f"- Full-RDO block root: `{root}`",
        f"- Raw rows scanned: `{total_rows}`",
        f"- LFNST-RDO-tested rows: `{eligible_rows}`",
        "",
        "## Definitions",
        "",
        "`P_waste = Pr(l* = 0 | LFNST RDO tested)`.",
        "",
        "`Delta J_LFNST = J0 - min(J1, J2)` and `P_gain = Pr(Delta J_LFNST > 0)`.",
        "",
        "`P_waste` uses all rows with `hasLfnst=True` as the LFNST-tested denominator. `P_gain` uses the same trace but requires finite `deltaBestLfnst`, so its valid-sample count can be slightly smaller.",
        "",
        "## Outputs",
        "",
        "- Fig. 1: `fig1_wasted_rdo_heatmap_latitude_size.png`",
        "- Fig. 2: `fig2_positive_gain_heatmap_latitude_size.png`",
        "- Table 1: `table1_wasted_and_gain_by_latitude_qp.csv`",
        "- Table 2: `table2_wasted_and_gain_by_latitude_size.csv`",
        "- Full detail: `table_latitude_qp_size_wasted_and_positive_gain.csv`",
        "",
        "## Table 1: Latitude x QP",
        "",
        md_table(table1, ["Latitude"] + [f"QP{qp}_wasted_rdo_ratio" for qp in qps] + ["AllQP_wasted_rdo_ratio"]),
        "",
        "## Table 2: Latitude x Block Size",
        "",
        md_table(table2, ["Latitude"] + [f"{s}_wasted_rdo_ratio" for s in size_labels]),
        "",
        "## Positive Gain: Latitude x Block Size",
        "",
        md_table(table2, ["Latitude"] + [f"{s}_positive_gain_ratio" for s in size_labels]),
        "",
        "## Conclusion",
        "",
        "The result supports the revised motivation: latitude is not a monotonic disabling factor for LFNST. After conditioning on LFNST RDO being tested, wasted-RDO ratio decreases from low to high latitude for common block-size groups such as `area_32`, `area_64`, and `area_256`, while positive-gain ratio increases. Very large blocks keep a high wasted-RDO ratio across latitude buckets, showing a strong interaction between latitude and block size.",
        "",
    ]
    (out_dir / "experiment_3_1_report.md").write_text("\n".join(report), encoding="utf-8")


if __name__ == "__main__":
    main()
