#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


FIELDS = (
    "latBin",
    "sizeId",
    "modeGroup",
    "setIdx",
    "transpose",
    "qpBucket",
    "supportRatioQ",
    "oxQ",
    "diagDominanceQ",
    "g1CovQ",
    "g2CovQ",
    "gmaxCovQ",
    "diffCovQ",
)
METRICS = ("oxQ", "diagDominanceQ", "gmaxCovQ", "diffCovQ")
GROUP_FIELDS = ("latBin", "sizeId", "setIdx", "transpose")
ROW_RE = re.compile(r"\{\s*([^{}]+?)\s*\},")


def _parse_rows(table_path: Path) -> list[dict[str, int]]:
    text = table_path.read_text(encoding="utf-8")
    rows: list[dict[str, int]] = []
    for match in ROW_RE.finditer(text):
        values = [int(part.strip()) for part in match.group(1).split(",")]
        if len(values) != len(FIELDS):
            continue
        rows.append(dict(zip(FIELDS, values)))
    if not rows:
        raise ValueError(f"no Skip21 theory rows found in {table_path}")
    return rows


def _percentile(sorted_values: list[int], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = pct * (len(sorted_values) - 1)
    lower = int(pos)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = pos - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def _metric_stats(values: Iterable[int]) -> dict[str, float]:
    sorted_values = sorted(values)
    return {
        "min": float(sorted_values[0]),
        "p10": _percentile(sorted_values, 0.10),
        "p50": _percentile(sorted_values, 0.50),
        "p90": _percentile(sorted_values, 0.90),
        "max": float(sorted_values[-1]),
    }


def _group_means(rows: list[dict[str, int]], field: str) -> dict[str, dict[str, float]]:
    grouped: dict[int, list[dict[str, int]]] = defaultdict(list)
    for row in rows:
        grouped[row[field]].append(row)
    result: dict[str, dict[str, float]] = {}
    for key, group_rows in sorted(grouped.items()):
        result[str(key)] = {
            "count": float(len(group_rows)),
            **{
                metric: sum(row[metric] for row in group_rows) / len(group_rows)
                for metric in METRICS
            },
        }
    return result


def _mode_group_qp_repetition(rows: list[dict[str, int]]) -> dict[str, Any]:
    grouped: dict[tuple[int, int, int, int], set[tuple[int, int, int, int]]] = defaultdict(set)
    for row in rows:
        key = (row["latBin"], row["sizeId"], row["setIdx"], row["transpose"])
        grouped[key].add(tuple(row[metric] for metric in METRICS))
    repeated = sum(1 for metric_sets in grouped.values() if len(metric_sets) == 1)
    return {
        "base_keys": len(grouped),
        "single_metric_set_keys": repeated,
        "varied_metric_set_keys": len(grouped) - repeated,
        "note": "modeGroup and qpBucket are preserved in the key; current template may repeat metrics across them.",
    }


def summarize_table(table_path: Path, out_path: Path | None = None) -> dict[str, Any]:
    rows = _parse_rows(table_path)
    summary: dict[str, Any] = {
        "table": str(table_path),
        "num_entries": len(rows),
        "metrics": {
            metric: _metric_stats(row[metric] for row in rows) for metric in METRICS
        },
        "group_means": {
            field: _group_means(rows, field) for field in GROUP_FIELDS
        },
        "mode_group_qp_repetition": _mode_group_qp_repetition(rows),
    }
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize the Skip21 Stage-2 theory table.")
    parser.add_argument(
        "--table",
        type=Path,
        default=Path("source/Lib/EncoderLib/LardLfnstSkip21TheoryTable.inc"),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("tools/lard_lfnst/skip21_theory_table_sanity.json"),
    )
    args = parser.parse_args()

    summary = summarize_table(args.table, args.out)
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"summary={args.out}")


if __name__ == "__main__":
    main()
