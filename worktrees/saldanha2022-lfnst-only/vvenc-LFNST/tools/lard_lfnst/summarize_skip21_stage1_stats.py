from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, DefaultDict, Dict, Optional


SUPPORT_BINS = (
    ("[0,0.25)", 0, 250),
    ("[0.25,0.5)", 250, 500),
    ("[0.5,0.75)", 500, 750),
    ("[0.75,1.0]", 750, 1001),
)


def _empty_accumulator() -> Dict[str, int]:
    return {
        "eligible_count": 0,
        "early_zero_count": 0,
        "candidate_before": 0,
        "candidate_after": 0,
    }


def _add_row(accumulator: Dict[str, int], row: Dict[str, str]) -> None:
    candidate_before = int(row["candidateBefore"])
    candidate_after = int(row["candidateAfter"])
    accumulator["eligible_count"] += 1
    accumulator["early_zero_count"] += int(int(row["earlyZero"]) != 0)
    accumulator["candidate_before"] += candidate_before
    accumulator["candidate_after"] += candidate_after


def _finish_accumulator(accumulator: Dict[str, int]) -> Dict[str, Any]:
    eligible_count = accumulator["eligible_count"]
    early_zero_count = accumulator["early_zero_count"]
    candidate_before = accumulator["candidate_before"]
    candidate_after = accumulator["candidate_after"]
    return {
        "eligible_count": eligible_count,
        "early_zero_count": early_zero_count,
        "early_zero_ratio": early_zero_count / eligible_count if eligible_count else 0.0,
        "candidate_before": candidate_before,
        "candidate_after": candidate_after,
        "candidate_reduction": (
            (candidate_before - candidate_after) / candidate_before
            if candidate_before
            else 0.0
        ),
    }


def _support_bin_name(support_ratio_q: int) -> str:
    for name, lower, upper in SUPPORT_BINS:
        if lower <= support_ratio_q < upper:
            return name
    raise ValueError(f"supportRatioQ outside supported bins: {support_ratio_q}")


def _finish_group(group: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, Any]]:
    return {key: _finish_accumulator(value) for key, value in sorted(group.items())}


def _read_final_lfnst_distribution(final_trace_csv: Path) -> Dict[str, int]:
    distribution: DefaultDict[str, int] = defaultdict(int)
    with final_trace_csv.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            distribution[row["lfnstIdx"]] += 1
    return dict(sorted(distribution.items()))


def summarize_stage1_stats(
    stage1_csv: Path, final_trace_csv: Optional[Path] = None
) -> Dict[str, Any]:
    total = _empty_accumulator()
    by_qp: DefaultDict[str, Dict[str, int]] = defaultdict(_empty_accumulator)
    by_size: DefaultDict[str, Dict[str, int]] = defaultdict(_empty_accumulator)
    by_lat_bin: DefaultDict[str, Dict[str, int]] = defaultdict(_empty_accumulator)
    by_support_bin: Dict[str, Dict[str, int]] = {
        name: _empty_accumulator() for name, _, _ in SUPPORT_BINS
    }

    with stage1_csv.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if int(row["candidateBefore"]) <= 0:
                continue

            _add_row(total, row)
            _add_row(by_qp[row["QP"]], row)
            _add_row(by_size[f"{row['w']}x{row['h']}"], row)
            _add_row(by_lat_bin[row["latBin"]], row)
            _add_row(by_support_bin[_support_bin_name(int(row["supportRatioQ"]))], row)

    total_finished = _finish_accumulator(total)
    return {
        "eligible_count": total_finished["eligible_count"],
        "early_zero_count": total_finished["early_zero_count"],
        "early_zero_ratio": total_finished["early_zero_ratio"],
        "candidate_before_total": total_finished["candidate_before"],
        "candidate_after_total": total_finished["candidate_after"],
        "nonzero_candidate_reduction": total_finished["candidate_reduction"],
        "by_qp": _finish_group(by_qp),
        "by_size": _finish_group(by_size),
        "by_lat_bin": _finish_group(by_lat_bin),
        "early_zero_by_support_ratio_bin": _finish_group(by_support_bin),
        "final_lfnst_idx_distribution": (
            _read_final_lfnst_distribution(final_trace_csv) if final_trace_csv else {}
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize skip21 stage-1 LFNST diagnostic CSVs."
    )
    parser.add_argument("--stage1-csv", required=True, type=Path)
    parser.add_argument("--final-trace-csv", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    summary = summarize_stage1_stats(args.stage1_csv, args.final_trace_csv)
    text = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    args.out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
