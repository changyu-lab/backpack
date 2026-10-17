#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, DefaultDict, Iterable, Sequence


ANCHOR_ADDITIONAL = "LFNST=1 LardLfnstSkip=0"
STAGE1_PROFILE_SPECS = (
    ("E5", 0),
    ("E10", 2),
    ("E12", 3),
    ("E15", 4),
    ("E12_noLat", 5),
    ("E15_noLat", 6),
)
STAGE2_PROFILE_SPECS = (
    ("S2_D1_only", -100),
    ("S2_D2_only", -101),
    ("S2_D3_only", -102),
)
PROFILE_SPECS = STAGE1_PROFILE_SPECS + STAGE2_PROFILE_SPECS
PROFILE_BY_NAME = dict(PROFILE_SPECS)
SUPPORT_BINS = (
    ("<=0.25", None, 250),
    ("0.25-0.35", 250, 350),
    ("0.35-0.45", 350, 450),
    ("0.45-0.55", 450, 550),
    ("0.55-0.60", 550, 600),
    ("0.60-0.65", 600, 650),
    (">0.65", 650, None),
)
GMAX_COV_BINS = (
    ("<=0.125", None, 128),
    ("0.125-0.25", 128, 256),
    ("0.25-0.50", 256, 512),
    ("0.50-0.75", 512, 768),
    (">0.75", 768, None),
    ("missing", None, None),
)
OX_BINS = (
    ("<=0.25", None, 256),
    ("0.25-0.35", 256, 358),
    ("0.35-0.50", 358, 512),
    ("0.50-0.75", 512, 768),
    (">0.75", 768, None),
    ("missing", None, None),
)
DIAG_DOMINANCE_BINS = (
    ("<=0.50", None, 512),
    ("0.50-0.625", 512, 640),
    ("0.625-0.75", 640, 768),
    ("0.75-0.875", 768, 896),
    (">0.875", 896, None),
    ("missing", None, None),
)
GROUP_FIELDS = (
    ("by_qp", "QP"),
    ("by_size", "size"),
    ("by_lat_bin", "latBin"),
    ("by_support_ratio_bin", "support_bin"),
    ("by_mode_group", "modeGroup"),
    ("by_setIdx", "setIdx"),
    ("by_transpose", "transpose"),
    ("by_ox_bin", "ox_bin"),
    ("by_diag_dominance_bin", "diag_dominance_bin"),
    ("by_gmax_cov_bin", "gmax_cov_bin"),
)
STAGE1_ID_FIELDS = (
    "QP",
    "x",
    "y",
    "w",
    "h",
    "latBin",
    "sizeId",
    "modeGroup",
    "setIdx",
    "transpose",
    "supportRatioQ",
)


def skip21_additional(profile: int) -> str:
    if profile <= -100:
        stage2_profile = -100 - profile
        return (
            "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 "
            f"LardLfnst21Stage2Profile={stage2_profile}"
        )
    return (
        "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=1 "
        f"LardLfnst21Profile={profile}"
    )


def find_aerialcity(sequence_root: Path) -> Path:
    patterns = (
        "AerialCity*3840x1920*420*erp*.yuv",
        "AerialCity*3840x1920*.yuv",
        "AerialCity*.yuv",
    )
    for pattern in patterns:
        matches = sorted(sequence_root.rglob(pattern))
        if matches:
            return matches[0]
    raise FileNotFoundError(f"could not find AerialCity YUV under {sequence_root}")


def additional_file_value(path: Path, base_dir: Path | None = None) -> str:
    """Return a vvenc --additional-safe file path, avoiding Windows drive colons."""
    base = base_dir if base_dir is not None else Path.cwd()
    try:
        return Path(os.path.relpath(path, base)).as_posix()
    except ValueError:
        return path.as_posix()


def _parse_qps(text: str) -> list[int]:
    return [int(value.strip()) for value in text.split(",") if value.strip()]


def _parse_profiles(text: str) -> list[tuple[str, int]]:
    names = [value.strip() for value in text.split(",") if value.strip()]
    if not names:
        raise ValueError("at least one profile is required")
    unknown = [name for name in names if name not in PROFILE_BY_NAME]
    if unknown:
        known = ", ".join(name for name, _ in PROFILE_SPECS)
        raise ValueError(f"unknown profile(s): {', '.join(unknown)}; known: {known}")
    return [(name, PROFILE_BY_NAME[name]) for name in names]


def _support_bin_name(support_ratio_q: int) -> str:
    for name, lower, upper in SUPPORT_BINS:
        lower_ok = True if lower is None else support_ratio_q > lower
        upper_ok = True if upper is None else support_ratio_q <= upper
        if lower_ok and upper_ok:
            return name
    raise ValueError(f"supportRatioQ outside supported bins: {support_ratio_q}")


def _gmax_cov_bin_name(gmax_cov_q: int | None) -> str:
    return _metric_bin_name(gmax_cov_q, GMAX_COV_BINS, ">0.75")


def _ox_bin_name(ox_q: int | None) -> str:
    return _metric_bin_name(ox_q, OX_BINS, ">0.75")


def _diag_dominance_bin_name(diag_dominance_q: int | None) -> str:
    return _metric_bin_name(diag_dominance_q, DIAG_DOMINANCE_BINS, ">0.875")


def _metric_bin_name(
    value_q: int | None,
    bins: tuple[tuple[str, int | None, int | None], ...],
    overflow: str,
) -> str:
    if value_q is None or value_q < 0:
        return "missing"
    for name, lower, upper in bins:
        if name == "missing":
            continue
        lower_ok = True if lower is None else value_q > lower
        upper_ok = True if upper is None else value_q <= upper
        if lower_ok and upper_ok:
            return name
    return overflow


def _empty_accumulator() -> dict[str, int]:
    return {
        "eligible_count": 0,
        "early_zero_count": 0,
        "stage1_early_zero_count": 0,
        "stage2_early_zero_count": 0,
        "s1_and_s2": 0,
        "s1_only": 0,
        "s2_only": 0,
        "neither": 0,
        "candidate_before": 0,
        "candidate_after": 0,
    }


def _add_row(acc: dict[str, int], row: dict[str, str]) -> None:
    candidate_before = int(row["candidateBefore"])
    candidate_after = int(row["candidateAfter"])
    stage1_early = int(row.get("stage1Decision", "0")) != 0
    stage2_early = int(row.get("stage2Decision", "0")) != 0
    acc["eligible_count"] += 1
    acc["early_zero_count"] += int(int(row["earlyZero"]) != 0)
    acc["stage1_early_zero_count"] += int(stage1_early)
    acc["stage2_early_zero_count"] += int(stage2_early)
    acc["s1_and_s2"] += int(stage1_early and stage2_early)
    acc["s1_only"] += int(stage1_early and not stage2_early)
    acc["s2_only"] += int(stage2_early and not stage1_early)
    acc["neither"] += int(not stage1_early and not stage2_early)
    acc["candidate_before"] += candidate_before
    acc["candidate_after"] += candidate_after


def _finish_accumulator(acc: dict[str, int]) -> dict[str, Any]:
    eligible_count = acc["eligible_count"]
    early_zero_count = acc["early_zero_count"]
    stage2_early_zero_count = acc["stage2_early_zero_count"]
    candidate_before = acc["candidate_before"]
    candidate_after = acc["candidate_after"]
    return {
        "eligible_count": eligible_count,
        "early_zero_count": early_zero_count,
        "stage1_early_zero_count": acc["stage1_early_zero_count"],
        "stage2_early_zero_count": stage2_early_zero_count,
        "stage2_early_zero_ratio": (
            stage2_early_zero_count / eligible_count if eligible_count else 0.0
        ),
        "overlap": {
            "s1_and_s2": acc["s1_and_s2"],
            "s1_only": acc["s1_only"],
            "s2_only": acc["s2_only"],
            "neither": acc["neither"],
        },
        "early_zero_ratio": early_zero_count / eligible_count if eligible_count else 0.0,
        "candidate_before": candidate_before,
        "candidate_after": candidate_after,
        "candidate_reduction": (
            (candidate_before - candidate_after) / candidate_before
            if candidate_before
            else 0.0
        ),
    }


def _finish_group(group: dict[str, dict[str, int]]) -> dict[str, dict[str, Any]]:
    return {key: _finish_accumulator(value) for key, value in sorted(group.items())}


def _read_stage1_rows(stage1_csv: Path) -> list[dict[str, str]]:
    return list(_iter_stage1_rows(stage1_csv))


def _iter_stage1_rows(stage1_csv: Path) -> Iterable[dict[str, str]]:
    with stage1_csv.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if int(row["candidateBefore"]) <= 0:
                continue
            row = dict(row)
            row["size"] = f"{row['w']}x{row['h']}"
            row["support_bin"] = _support_bin_name(int(row["supportRatioQ"]))
            row["stage2Decision"] = row.get("stage2Decision", "0")
            gmax_text = row.get("gmaxCovQ", "")
            ox_text = row.get("oxQ", "")
            diag_text = row.get("diagDominanceQ", "")
            row["ox_bin"] = _ox_bin_name(int(ox_text) if ox_text else None)
            row["diag_dominance_bin"] = _diag_dominance_bin_name(int(diag_text) if diag_text else None)
            row["gmax_cov_bin"] = _gmax_cov_bin_name(int(gmax_text) if gmax_text else None)
            yield row


def _stage1_identity(row: dict[str, str]) -> tuple[str, ...]:
    return tuple(row[field] for field in STAGE1_ID_FIELDS)


def _final_match_key_from_stage1(row: dict[str, str]) -> tuple[str, str, str, str, str]:
    return (row["QP"], row["x"], row["y"], row["w"], row["h"])


def _final_match_key_from_trace(row: dict[str, str]) -> tuple[str, str, str, str, str]:
    return (row["qp"], row["x"], row["y"], row["w"], row["h"])


def _read_anchor_final(final_trace_csv: Path) -> tuple[dict[str, int], dict[tuple[str, str, str, str, str], list[str]]]:
    all_distribution: Counter[str] = Counter()
    by_key: DefaultDict[tuple[str, str, str, str, str], list[str]] = defaultdict(list)
    with final_trace_csv.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            idx = row["lfnstIdx"]
            all_distribution[idx] += 1
            by_key[_final_match_key_from_trace(row)].append(idx)
    return dict(sorted(all_distribution.items())), dict(by_key)


def _matched_final_distribution(
    rows: Iterable[dict[str, str]],
    anchor_final_by_key: dict[tuple[str, str, str, str, str], list[str]],
) -> tuple[dict[str, int], int]:
    distribution: Counter[str] = Counter()
    unmatched = 0
    for row in rows:
        matches = anchor_final_by_key.get(_final_match_key_from_stage1(row), [])
        if not matches:
            unmatched += 1
            continue
        distribution.update(matches)
    return dict(sorted(distribution.items())), unmatched


def _summarize_rows(
    rows: list[dict[str, str]],
    anchor_final_by_key: dict[tuple[str, str, str, str, str], list[str]] | None = None,
) -> dict[str, Any]:
    total, groups = _new_stream_state()
    for row in rows:
        _add_stream_row(total, groups, row)

    early_rows = [row for row in rows if int(row["earlyZero"]) != 0]
    early_distribution: dict[str, int] = {}
    unmatched = 0
    if anchor_final_by_key is not None:
        early_distribution, unmatched = _matched_final_distribution(
            early_rows, anchor_final_by_key
        )

    total_finished = _finish_accumulator(total)
    summary: dict[str, Any] = {
        "total_lfnst_eligible": total_finished["eligible_count"],
        "stage1_checked": total_finished["eligible_count"],
        "stage2_checked": total_finished["eligible_count"],
        "early_zero_count": total_finished["early_zero_count"],
        "stage1_early_zero_count": total_finished["stage1_early_zero_count"],
        "stage2_early_zero_count": total_finished["stage2_early_zero_count"],
        "stage2_early_zero_ratio": total_finished["stage2_early_zero_ratio"],
        "overlap": total_finished["overlap"],
        "both_count": total_finished["overlap"]["s1_and_s2"],
        "stage1_only_count": total_finished["overlap"]["s1_only"],
        "stage2_only_count": total_finished["overlap"]["s2_only"],
        "neither_count": total_finished["overlap"]["neither"],
        "early_zero_ratio": total_finished["early_zero_ratio"],
        "candidate_before_total": total_finished["candidate_before"],
        "candidate_after_total": total_finished["candidate_after"],
        "nonzero_candidate_reduction": total_finished["candidate_reduction"],
    }
    for section, _ in GROUP_FIELDS:
        summary[section] = _finish_group(groups[section])
    if anchor_final_by_key is not None:
        summary["anchor_final_idx_distribution_early_zero"] = early_distribution
        summary["anchor_final_idx_unmatched_early_zero"] = unmatched
    return summary


def _new_stream_state() -> tuple[dict[str, int], dict[str, DefaultDict[str, dict[str, int]]]]:
    return (
        _empty_accumulator(),
        {section: defaultdict(_empty_accumulator) for section, _ in GROUP_FIELDS},
    )


def _add_stream_row(
    total: dict[str, int],
    groups: dict[str, DefaultDict[str, dict[str, int]]],
    row: dict[str, str],
) -> None:
    _add_row(total, row)
    for section, field in GROUP_FIELDS:
        _add_row(groups[section][row[field]], row)


def _finish_stream_summary(
    total: dict[str, int],
    groups: dict[str, DefaultDict[str, dict[str, int]]],
    final_distribution_key: str | None = None,
    final_distribution: Counter[str] | None = None,
    unmatched_key: str | None = None,
    unmatched: int = 0,
) -> dict[str, Any]:
    total_finished = _finish_accumulator(total)
    summary: dict[str, Any] = {
        "total_lfnst_eligible": total_finished["eligible_count"],
        "stage1_checked": total_finished["eligible_count"],
        "stage2_checked": total_finished["eligible_count"],
        "early_zero_count": total_finished["early_zero_count"],
        "stage1_early_zero_count": total_finished["stage1_early_zero_count"],
        "stage2_early_zero_count": total_finished["stage2_early_zero_count"],
        "stage2_early_zero_ratio": total_finished["stage2_early_zero_ratio"],
        "overlap": total_finished["overlap"],
        "both_count": total_finished["overlap"]["s1_and_s2"],
        "stage1_only_count": total_finished["overlap"]["s1_only"],
        "stage2_only_count": total_finished["overlap"]["s2_only"],
        "neither_count": total_finished["overlap"]["neither"],
        "early_zero_ratio": total_finished["early_zero_ratio"],
        "candidate_before_total": total_finished["candidate_before"],
        "candidate_after_total": total_finished["candidate_after"],
        "nonzero_candidate_reduction": total_finished["candidate_reduction"],
    }
    for section, _ in GROUP_FIELDS:
        summary[section] = _finish_group(groups[section])
    if final_distribution_key is not None and final_distribution is not None:
        summary[final_distribution_key] = dict(sorted(final_distribution.items()))
    if unmatched_key is not None:
        summary[unmatched_key] = unmatched
    return summary


def _add_matched_final_distribution(
    row: dict[str, str],
    anchor_final_by_key: dict[tuple[str, str, str, str, str], list[str]],
    distribution: Counter[str],
) -> int:
    matches = anchor_final_by_key.get(_final_match_key_from_stage1(row), [])
    if not matches:
        return 1
    distribution.update(matches)
    return 0


def _summarize_stage1_csv_streaming(
    stage1_csv: Path,
    anchor_final_by_key: dict[tuple[str, str, str, str, str], list[str]],
    collect_early_counter: bool = False,
    consume_early_counter: Counter[tuple[str, ...]] | None = None,
    extra_label: str = "E10",
) -> tuple[dict[str, Any], Counter[tuple[str, ...]], dict[str, Any] | None]:
    total, groups = _new_stream_state()
    early_final_distribution: Counter[str] = Counter()
    unmatched_early = 0
    collected_early: Counter[tuple[str, ...]] = Counter()

    extra_total, extra_groups = _new_stream_state()
    extra_final_distribution: Counter[str] = Counter()
    unmatched_extra = 0

    for row in _iter_stage1_rows(stage1_csv):
        _add_stream_row(total, groups, row)
        if int(row["earlyZero"]) == 0:
            continue

        unmatched_early += _add_matched_final_distribution(
            row, anchor_final_by_key, early_final_distribution
        )
        identity = _stage1_identity(row)
        if collect_early_counter:
            collected_early[identity] += 1
        if consume_early_counter is None:
            continue
        if consume_early_counter[identity] > 0:
            consume_early_counter[identity] -= 1
            continue
        _add_stream_row(extra_total, extra_groups, row)
        unmatched_extra += _add_matched_final_distribution(
            row, anchor_final_by_key, extra_final_distribution
        )

    profile_summary = _finish_stream_summary(
        total,
        groups,
        "anchor_final_idx_distribution_early_zero",
        early_final_distribution,
        "anchor_final_idx_unmatched_early_zero",
        unmatched_early,
    )
    extra_summary = None
    if consume_early_counter is not None:
        extra_summary = _finish_stream_summary(
            extra_total,
            extra_groups,
            f"anchor_final_idx_distribution_{extra_label}_extra",
            extra_final_distribution,
            f"anchor_final_idx_unmatched_{extra_label}_extra",
            unmatched_extra,
        )
    return profile_summary, collected_early, extra_summary


def _empty_extra_summary(
    anchor_final_by_key: dict[tuple[str, str, str, str, str], list[str]],
    extra_label: str,
) -> dict[str, Any]:
    extra_summary = _summarize_rows([], anchor_final_by_key)
    extra_summary[f"anchor_final_idx_distribution_{extra_label}_extra"] = (
        extra_summary.pop("anchor_final_idx_distribution_early_zero")
    )
    extra_summary[f"anchor_final_idx_unmatched_{extra_label}_extra"] = (
        extra_summary.pop("anchor_final_idx_unmatched_early_zero")
    )
    return extra_summary


def _counter_size(counter: Counter[tuple[str, ...]]) -> int:
    return sum(counter.values())


def _counter_intersection_size(
    lhs: Counter[tuple[str, ...]], rhs: Counter[tuple[str, ...]]
) -> int:
    return sum((lhs & rhs).values())


def _early_overlap_summary(
    stage1_e15_nolat: Counter[tuple[str, ...]],
    other: Counter[tuple[str, ...]],
    total_eligible: int,
) -> dict[str, int]:
    both = _counter_intersection_size(stage1_e15_nolat, other)
    stage1_count = _counter_size(stage1_e15_nolat)
    other_count = _counter_size(other)
    union_count = stage1_count + other_count - both
    return {
        "stage1_e15_nolat_count": stage1_count,
        "stage2_count": other_count,
        "both_count": both,
        "stage1_only_count": stage1_count - both,
        "stage2_only_count": other_count - both,
        "neither_count": max(0, total_eligible - union_count),
    }


def _finish_extra_view(extra_summary: dict[str, Any]) -> dict[str, Any]:
    for section, _ in GROUP_FIELDS:
        extra_summary[f"delta_early_zero_{section}"] = extra_summary.pop(section)
    extra_summary["anchor_final_join_key"] = "QP,x,y,w,h"
    return extra_summary


def _e10_extra_rows(
    e5_rows: list[dict[str, str]], e10_rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    e5_early = Counter(
        _stage1_identity(row) for row in e5_rows if int(row["earlyZero"]) != 0
    )
    extra: list[dict[str, str]] = []
    for row in e10_rows:
        if int(row["earlyZero"]) == 0:
            continue
        identity = _stage1_identity(row)
        if e5_early[identity] > 0:
            e5_early[identity] -= 1
        else:
            extra.append(row)
    return extra


def summarize_profiles(
    profile_stage1_csvs: dict[str, Path], anchor_final_trace_csv: Path
) -> dict[str, Any]:
    anchor_final_all, anchor_final_by_key = _read_anchor_final(anchor_final_trace_csv)

    profiles: dict[str, dict[str, Any]] = {}
    baseline_early_counters: dict[str, Counter[tuple[str, ...]]] = {}
    extra_summaries: dict[str, dict[str, Any]] = {}
    extra_baselines = {
        "E10": "E5",
        "E12": "E10",
        "E15": "E10",
        "E12_noLat": "E12",
        "E15_noLat": "E15",
    }
    ordered_names = [
        name
        for name in ("E5", "E10", "E12", "E15", "E12_noLat", "E15_noLat")
        if name in profile_stage1_csvs
    ] + sorted(
        name
        for name in profile_stage1_csvs
        if name not in {"E5", "E10", "E12", "E15", "E12_noLat", "E15_noLat"}
    )
    for name in ordered_names:
        baseline_name = extra_baselines.get(name)
        consume_counter = (
            baseline_early_counters[baseline_name].copy()
            if baseline_name in baseline_early_counters
            else None
        )
        summary, early_counter, extra_summary = _summarize_stage1_csv_streaming(
            profile_stage1_csvs[name],
            anchor_final_by_key,
            collect_early_counter=(name in {"E5", "E10", "E12", "E15", "E15_noLat"} or name.startswith("S2_")),
            consume_early_counter=consume_counter,
            extra_label=name,
        )
        summary["anchor_final_idx_distribution_all"] = anchor_final_all
        summary["anchor_final_join_key"] = "QP,x,y,w,h"
        profiles[name] = summary
        if name in {"E5", "E10", "E12", "E15", "E15_noLat"} or name.startswith("S2_"):
            baseline_early_counters[name] = early_counter
        if extra_summary is not None and baseline_name is not None:
            extra_summaries[f"{name.lower()}_extra_vs_{baseline_name.lower()}"] = (
                _finish_extra_view(extra_summary)
            )

    if "E15_noLat" in baseline_early_counters:
        e15_counter = baseline_early_counters["E15_noLat"]
        for name, summary in profiles.items():
            if name == "E15_noLat":
                continue
            if name not in baseline_early_counters:
                continue
            summary["overlap_with_stage1_e15_nolat"] = _early_overlap_summary(
                e15_counter,
                baseline_early_counters[name],
                int(summary["total_lfnst_eligible"]),
            )

    for name, baseline_name in extra_baselines.items():
        key = f"{name.lower()}_extra_vs_{baseline_name.lower()}"
        if name in profile_stage1_csvs and baseline_name in profile_stage1_csvs and key not in extra_summaries:
            extra_summaries[key] = _finish_extra_view(
                _empty_extra_summary(anchor_final_by_key, name)
            )

    return {"profiles": profiles, **extra_summaries}


def _qps_arg(qps: Sequence[int]) -> str:
    return ",".join(str(qp) for qp in qps)


def _diagnostic_command(
    encoder: Path,
    orig: Path,
    out_dir: Path,
    qp: int,
    width: int,
    height: int,
    threads: int,
    preset: str,
    frames: int,
    additional: str,
) -> list[str]:
    return [
        str(encoder),
        "--preset",
        preset,
        "-i",
        str(orig),
        "-s",
        f"{width}x{height}",
        "-r",
        "30",
        "--InputChromaFormat",
        "420",
        "-q",
        str(qp),
        "--qpa",
        "0",
        "-f",
        str(frames),
        "-ip",
        "1",
        "--mtprofile",
        "0",
        "--threads",
        str(threads),
        "--additional",
        additional,
        "-b",
        str(out_dir / f"QP{qp}.vvc"),
        "-o",
        str(out_dir / f"QP{qp}_rec.yuv"),
    ]


def _final_trace_csv(trace_base: Path) -> Path:
    return Path(str(trace_base) + ".final.csv")


def _prepare_fresh(paths: Iterable[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def _require_fresh_nonempty(path: Path, started_at: float) -> None:
    if not path.exists():
        raise RuntimeError(f"expected output was not created: {path}")
    stat = path.stat()
    if stat.st_size <= 0:
        raise RuntimeError(f"expected output is empty: {path}")
    if stat.st_mtime < started_at:
        raise RuntimeError(f"expected output is stale: {path}")


def _concat_csvs(csv_paths: Sequence[Path], out_csv: Path) -> None:
    if not csv_paths:
        raise ValueError("at least one CSV is required")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = None
    with out_csv.open("w", newline="", encoding="utf-8") as out_handle:
        writer = None
        for csv_path in csv_paths:
            with csv_path.open(newline="", encoding="utf-8-sig") as in_handle:
                reader = csv.DictReader(in_handle)
                if reader.fieldnames is None:
                    raise ValueError(f"CSV has no header: {csv_path}")
                if fieldnames is None:
                    fieldnames = list(reader.fieldnames)
                    writer = csv.DictWriter(out_handle, fieldnames=fieldnames)
                    writer.writeheader()
                elif list(reader.fieldnames) != fieldnames:
                    raise ValueError(f"CSV header mismatch: {csv_path}")
                assert writer is not None
                for row in reader:
                    writer.writerow(row)


def _run_encode_and_cleanup(
    cmd: list[str], required_outputs: Sequence[Path], cleanup_outputs: Sequence[Path]
) -> None:
    _prepare_fresh([*required_outputs, *cleanup_outputs])
    started_at = time.time()
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)
    for path in required_outputs:
        _require_fresh_nonempty(path, started_at)
    for path in cleanup_outputs:
        path.unlink(missing_ok=True)


def anchor_cleanup_outputs(out_dir: Path, qp: int, trace_base: Path) -> list[Path]:
    return [trace_base, out_dir / f"QP{qp}.vvc", out_dir / f"QP{qp}_rec.yuv"]


def run_diagnostics(args: argparse.Namespace, qps: Sequence[int]) -> dict[str, Any]:
    args.out_root.mkdir(parents=True, exist_ok=True)
    anchor_final_csvs: list[Path] = []
    profile_specs = getattr(args, "profiles", STAGE1_PROFILE_SPECS)
    profile_stage1_csvs: dict[str, list[Path]] = {name: [] for name, _ in profile_specs}

    for qp in qps:
        out_dir = args.out_root / "ANCHOR" / f"QP{qp}"
        out_dir.mkdir(parents=True, exist_ok=True)
        trace_base = out_dir / "trace.csv"
        final_trace_csv = _final_trace_csv(trace_base)
        trace_value = additional_file_value(trace_base)
        additional = f"{ANCHOR_ADDITIONAL} LardLfnstTraceFile={trace_value}"
        cmd = _diagnostic_command(
            args.encoder,
            args.orig,
            out_dir,
            qp,
            args.width,
            args.height,
            args.threads,
            args.preset,
            args.frames,
            additional,
        )
        _run_encode_and_cleanup(
            cmd,
            [final_trace_csv],
            anchor_cleanup_outputs(out_dir, qp, trace_base),
        )
        anchor_final_csvs.append(final_trace_csv)

    for profile_name, profile in profile_specs:
        for qp in qps:
            out_dir = args.out_root / profile_name / f"QP{qp}"
            out_dir.mkdir(parents=True, exist_ok=True)
            stage1_csv = out_dir / "stage1.csv"
            additional = (
                f"{skip21_additional(profile)} "
                f"LardLfnst21StatFile={additional_file_value(stage1_csv)}"
            )
            cmd = _diagnostic_command(
                args.encoder,
                args.orig,
                out_dir,
                qp,
                args.width,
                args.height,
                args.threads,
                args.preset,
                args.frames,
                additional,
            )
            _run_encode_and_cleanup(
                cmd,
                [stage1_csv],
                [out_dir / f"QP{qp}.vvc", out_dir / f"QP{qp}_rec.yuv"],
            )
            profile_stage1_csvs[profile_name].append(stage1_csv)

    merged_dir = args.out_root / "merged"
    anchor_final = merged_dir / "anchor_final_trace.csv"
    _concat_csvs(anchor_final_csvs, anchor_final)
    merged_stage1: dict[str, Path] = {}
    for profile_name, csv_paths in profile_stage1_csvs.items():
        out_csv = merged_dir / f"{profile_name}_stage1.csv"
        _concat_csvs(csv_paths, out_csv)
        merged_stage1[profile_name] = out_csv

    summary = summarize_profiles(merged_stage1, anchor_final)
    summary["configuration"] = {
        "orig": str(args.orig),
        "encoder": str(args.encoder),
        "qps": _qps_arg(qps),
        "profiles": ",".join(name for name, _ in profile_specs),
        "width": args.width,
        "height": args.height,
        "frames": args.frames,
        "threads": args.threads,
        "preset": args.preset,
        "anchor_additional": ANCHOR_ADDITIONAL,
        "E5_additional": skip21_additional(0),
        "E10_additional": skip21_additional(2),
        "E12_additional": skip21_additional(3),
        "E15_additional": skip21_additional(4),
        "E12_noLat_additional": skip21_additional(5),
        "E15_noLat_additional": skip21_additional(6),
        "join_note": (
            "anchor final lfnstIdx distributions for early-zero rows are matched "
            "by QP,x,y,w,h. Use --frames 1 for exact geometry matching; multi-frame "
            "runs may contain repeated geometry."
        ),
    }
    summary["merged_files"] = {"anchor_final_trace_csv": str(anchor_final)}
    summary["merged_files"].update(
        {f"{profile_name}_stage1_csv": str(path) for profile_name, path in merged_stage1.items()}
    )
    summary_path = args.out_root / "skip21_stage1_diagnostic_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
    print(f"summary={summary_path}", flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Skip21 Stage-1 diagnostic summary without timing claims."
    )
    parser.add_argument("--encoder", type=Path, default=Path("bin") / "vvencFFapp.exe")
    parser.add_argument("--sequence-root", type=Path, default=Path(r"F:\Sequences360"))
    parser.add_argument("--orig", type=Path, default=None)
    parser.add_argument("--out-root", type=Path, default=Path("runs") / "skip21_stage1_diagnostics")
    parser.add_argument("--qps", default="22,27,32,37")
    parser.add_argument(
        "--profiles",
        default=",".join(name for name, _ in STAGE1_PROFILE_SPECS),
        help="Comma-separated profile names to diagnose. Known: "
        + ",".join(name for name, _ in PROFILE_SPECS),
    )
    parser.add_argument("--width", type=int, default=3840)
    parser.add_argument("--height", type=int, default=1920)
    parser.add_argument("--frames", type=int, default=1)
    parser.add_argument("--threads", type=int, default=20)
    parser.add_argument("--preset", default="medium")
    args = parser.parse_args()

    args.encoder = args.encoder.resolve()
    args.orig = args.orig.resolve() if args.orig else find_aerialcity(args.sequence_root)
    args.out_root = args.out_root.resolve()
    if not args.encoder.exists():
        raise FileNotFoundError(args.encoder)
    if not args.orig.exists():
        raise FileNotFoundError(args.orig)
    args.profiles = _parse_profiles(args.profiles)

    run_diagnostics(args, _parse_qps(args.qps))


if __name__ == "__main__":
    main()
