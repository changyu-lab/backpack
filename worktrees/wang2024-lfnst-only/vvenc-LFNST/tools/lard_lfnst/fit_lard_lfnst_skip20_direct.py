#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, TextIO, Tuple

import numpy as np


MASKS = {
    0x1: (0,),
    0x3: (0, 1),
    0x5: (0, 2),
    0x7: (0, 1, 2),
}
MASK_LABELS = {0x1: "0", 0x3: "0,1", 0x5: "0,2", 0x7: "0,1,2"}
REQUIRED_FIELDS = {
    "J0", "J1", "J2",
    "candidateRdoTimeNs1", "candidateRdoTimeNs2",
    "actualCuQp", "W", "H", "setIdx", "transpose", "latBin", "modeGroup",
    "baseRoiEnergy", "baseNnz", "baseLast", "qStep", "tableFound",
}

LEVELS = (
    "full",
    "no_last",
    "no_nnz",
    "no_mode",
    "no_lat",
    "core",
)
LEVEL_IDS = {name: idx for idx, name in enumerate(LEVELS)}


@dataclass(frozen=True)
class Row:
    costs: tuple[float, float, float]
    times: tuple[float, float, float]
    qp: int
    width: int
    height: int
    set_idx: int
    transpose: int
    lat_bin: int
    mode_group: int
    energy_q: float
    base_nnz: int
    base_last: int


@dataclass(frozen=True)
class Bins:
    energy: int
    nnz: int
    last: int


@dataclass(frozen=True)
class MaskAggregate:
    sum_saved: float
    sum_loss: float
    p95_relative_loss: float


CutTable = Dict[Tuple[int, int, int], Tuple[float, ...]]
Thresholds = Dict[str, CutTable]
Key = Tuple[int, ...]
LevelTables = Dict[str, Dict[Key, int]]
HierarchyStats = Dict[str, Dict[Key, Dict[int, MaskAggregate]]]


def open_text(path: Path) -> TextIO:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", newline="", encoding="utf-8")
    return path.open("r", newline="", encoding="utf-8")


def load_rows(paths: Iterable[Path]) -> list[Row]:
    rows: list[Row] = []
    for path in paths:
        with open_text(path) as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or ())
            missing = sorted(REQUIRED_FIELDS - fields)
            if missing:
                raise ValueError(f"{path}: missing required columns: {', '.join(missing)}")
            for raw in reader:
                try:
                    if not int(raw["tableFound"]):
                        continue
                    if not all(int(raw.get(f"rdoValid{idx}", "1")) for idx in range(3)):
                        continue
                    costs = tuple(float(raw[f"J{idx}"]) for idx in range(3))
                    if not all(math.isfinite(value) for value in costs):
                        continue
                    q_step = float(raw["qStep"])
                    energy_q = max(0.0, float(raw["baseRoiEnergy"])) / max(1e-12, q_step * q_step)
                    rows.append(
                        Row(
                            costs=costs,
                            times=(
                                0.0,
                                max(0.0, float(raw["candidateRdoTimeNs1"])),
                                max(0.0, float(raw["candidateRdoTimeNs2"])),
                            ),
                            qp=int(raw["actualCuQp"]),
                            width=int(raw["W"]),
                            height=int(raw["H"]),
                            set_idx=int(raw["setIdx"]),
                            transpose=int(raw["transpose"]),
                            lat_bin=int(raw["latBin"]),
                            mode_group=int(raw["modeGroup"]),
                            energy_q=energy_q,
                            base_nnz=max(0, int(raw["baseNnz"])),
                            base_last=int(raw["baseLast"]),
                        )
                    )
                except (KeyError, TypeError, ValueError):
                    continue
    return rows


def mask_metrics(row: Row, mask: int) -> tuple[float, float, float, int]:
    best = min(row.costs)
    retained_cost = min(row.costs[idx] for idx in MASKS[mask])
    loss = max(0.0, retained_cost - best)
    relative_loss = loss / max(1.0, abs(best))
    removed = tuple(idx for idx in (1, 2) if idx not in MASKS[mask])
    saved = sum(row.times[idx] for idx in removed)
    return saved, loss, relative_loss, len(removed)


def unique_quantile_cuts(samples: list[float], bins: int) -> tuple[float, ...]:
    if bins <= 1 or not samples:
        return ()
    values = np.quantile(samples, [idx / bins for idx in range(1, bins)])
    cuts: list[float] = []
    for value in values:
        cut = float(value)
        if not cuts or cut > cuts[-1]:
            cuts.append(cut)
    return tuple(cuts)


def build_cut_table(rows: list[Row], bins: int, value: Callable[[Row], float]) -> CutTable:
    grouped: dict[tuple[int, int, int], list[float]] = defaultdict(list)
    for row in rows:
        grouped[(row.qp, row.width, row.height)].append(value(row))
    return {key: unique_quantile_cuts(samples, bins) for key, samples in grouped.items()}


def build_thresholds(rows: list[Row], energy_bins: int, nnz_bins: int, last_bins: int) -> Thresholds:
    return {
        "energy": build_cut_table(rows, energy_bins, lambda row: row.energy_q),
        "nnz": build_cut_table(rows, nnz_bins, lambda row: float(row.base_nnz)),
        "last": build_cut_table(rows, last_bins, lambda row: float(row.base_last)),
    }


def row_bins(row: Row, thresholds: Thresholds) -> Bins:
    group = (row.qp, row.width, row.height)
    if any(group not in thresholds[name] for name in ("energy", "nnz", "last")):
        return Bins(-1, -1, -1)
    return Bins(
        bisect.bisect_right(thresholds["energy"][group], row.energy_q),
        bisect.bisect_right(thresholds["nnz"][group], row.base_nnz),
        bisect.bisect_right(thresholds["last"][group], row.base_last),
    )


def projected_key(row: Row, bins: Bins, level: str) -> Key:
    mode = row.mode_group
    set_idx = row.set_idx
    transpose = row.transpose
    lat = row.lat_bin
    nnz = bins.nnz
    last = bins.last
    if level in ("no_last", "no_nnz", "no_mode", "no_lat", "core"):
        last = -1
    if level in ("no_nnz", "no_mode", "no_lat", "core"):
        nnz = -1
    if level in ("no_mode", "no_lat", "core"):
        mode = -1
    if level in ("no_lat", "core"):
        lat = -1
    if level == "core":
        set_idx = -1
        transpose = -1
    return (
        row.qp,
        row.width,
        row.height,
        mode,
        set_idx,
        transpose,
        lat,
        bins.energy,
        nnz,
        last,
    )


def aggregate_group(samples: list[Row]) -> dict[int, MaskAggregate]:
    aggregates: dict[int, MaskAggregate] = {}
    for mask in MASKS:
        metrics = [mask_metrics(row, mask) for row in samples]
        aggregates[mask] = MaskAggregate(
            sum_saved=sum(item[0] for item in metrics),
            sum_loss=sum(item[1] for item in metrics),
            p95_relative_loss=float(np.quantile([item[2] for item in metrics], 0.95)),
        )
    return aggregates


def choose_group_mask(aggregates: dict[int, MaskAggregate], mu: float, max_p95_relative_loss: float) -> int:
    options: list[tuple[float, float, float, int]] = []
    for mask, aggregate in aggregates.items():
        if mask != 0x7 and aggregate.p95_relative_loss > max_p95_relative_loss:
            continue
        score = aggregate.sum_saved - mu * aggregate.sum_loss
        options.append((score, -aggregate.sum_loss, aggregate.sum_saved, mask))
    return max(options)[3]


def build_hierarchy_stats(
    rows: list[Row],
    thresholds: Thresholds,
    min_samples: int,
) -> HierarchyStats:
    stats: HierarchyStats = {}
    for level in LEVELS:
        groups: dict[Key, list[Row]] = defaultdict(list)
        for row in rows:
            bins = row_bins(row, thresholds)
            if bins.energy < 0:
                continue
            groups[projected_key(row, bins, level)].append(row)
        level_stats: dict[Key, dict[int, MaskAggregate]] = {}
        for key, samples in groups.items():
            if len(samples) >= min_samples:
                level_stats[key] = aggregate_group(samples)
        stats[level] = level_stats
    return stats


def train_hierarchy_from_stats(
    stats: HierarchyStats,
    mu: float,
    max_p95_relative_loss: float,
) -> LevelTables:
    tables: LevelTables = {}
    for level in LEVELS:
        # Store full-RDO decisions as well. They stop a finer, sufficiently
        # sampled bucket from falling through to an aggressive parent.
        tables[level] = {
            key: choose_group_mask(aggregates, mu, max_p95_relative_loss)
            for key, aggregates in stats[level].items()
        }
    return tables


def train_hierarchy(
    rows: list[Row],
    thresholds: Thresholds,
    mu: float,
    min_samples: int,
    max_p95_relative_loss: float,
) -> LevelTables:
    return train_hierarchy_from_stats(
        build_hierarchy_stats(rows, thresholds, min_samples),
        mu,
        max_p95_relative_loss,
    )


def lookup_mask(row: Row, thresholds: Thresholds, tables: LevelTables) -> tuple[int, str]:
    bins = row_bins(row, thresholds)
    if bins.energy < 0:
        return 0x7, "full_rdo"
    for level in LEVELS:
        key = projected_key(row, bins, level)
        if key in tables[level]:
            return tables[level][key], level
    return 0x7, "full_rdo"


def empty_breakdown() -> dict[str, object]:
    return {
        "rows": 0,
        "saved_ns": 0.0,
        "rd_loss": 0.0,
        "removed_candidates": 0,
        "mask_counts": Counter(),
        "fallback_counts": Counter(),
    }


def update_breakdown(target: dict[str, object], mask: int, level: str, metrics: tuple[float, float, float, int]) -> None:
    target["rows"] = int(target["rows"]) + 1
    target["saved_ns"] = float(target["saved_ns"]) + metrics[0]
    target["rd_loss"] = float(target["rd_loss"]) + metrics[1]
    target["removed_candidates"] = int(target["removed_candidates"]) + metrics[3]
    target["mask_counts"][MASK_LABELS[mask]] += 1  # type: ignore[index]
    target["fallback_counts"][level] += 1  # type: ignore[index]


def finalize_breakdown(raw: dict[str, object]) -> dict[str, object]:
    rows = int(raw["rows"])
    return {
        "rows": rows,
        "saved_ns": int(round(float(raw["saved_ns"]))),
        "rd_loss": float(raw["rd_loss"]),
        "removed_candidates": int(raw["removed_candidates"]),
        "candidate_reduction": int(raw["removed_candidates"]) / (2 * rows) if rows else 0.0,
        "mask_counts": {
            label: int(raw["mask_counts"].get(label, 0))  # type: ignore[union-attr]
            for label in MASK_LABELS.values()
        },
        "fallback_counts": {
            level: int(raw["fallback_counts"].get(level, 0))  # type: ignore[union-attr]
            for level in (*LEVELS, "full_rdo")
        },
    }


def replay(
    rows: list[Row],
    thresholds: Thresholds,
    tables: LevelTables,
    anchor_time_ns: float | None = None,
    candidate_time_total_ns: float | None = None,
    intra_time_total_ns: float | None = None,
) -> dict[str, object]:
    total_candidate_time = sum(row.times[1] + row.times[2] for row in rows)
    total_best_cost = sum(max(1.0, abs(min(row.costs))) for row in rows)
    overall = empty_breakdown()
    by_qp: dict[str, dict[str, object]] = defaultdict(empty_breakdown)
    by_size: dict[str, dict[str, object]] = defaultdict(empty_breakdown)
    for row in rows:
        mask, level = lookup_mask(row, thresholds, tables)
        metrics = mask_metrics(row, mask)
        update_breakdown(overall, mask, level, metrics)
        update_breakdown(by_qp[str(row.qp)], mask, level, metrics)
        update_breakdown(by_size[f"{row.width}x{row.height}"], mask, level, metrics)
    result = finalize_breakdown(overall)
    saved = float(overall["saved_ns"])
    rd_loss = float(overall["rd_loss"])
    time_saving_ratio = saved / total_candidate_time if total_candidate_time else 0.0
    if candidate_time_total_ns and candidate_time_total_ns > 0 and intra_time_total_ns and intra_time_total_ns > 0:
        ts_proxy = 100.0 * time_saving_ratio * candidate_time_total_ns / intra_time_total_ns
        ts_denominator = intra_time_total_ns
        calibration = "full_candidate_over_intra"
    else:
        ts_denominator = anchor_time_ns if anchor_time_ns and anchor_time_ns > 0 else total_candidate_time
        ts_proxy = 100.0 * saved / ts_denominator if ts_denominator else 0.0
        calibration = "sample_saved_over_anchor" if anchor_time_ns else "sample_candidate_ratio"
    rd_proxy = 100.0 * rd_loss / total_best_cost if total_best_cost else 0.0
    result.update(
        {
            "total_candidate_time_ns": int(round(total_candidate_time)),
            "anchor_time_ns": int(round(ts_denominator)),
            "candidate_time_total_ns": int(round(candidate_time_total_ns)) if candidate_time_total_ns else None,
            "intra_time_total_ns": int(round(intra_time_total_ns)) if intra_time_total_ns else None,
            "ts_proxy_calibration": calibration,
            "total_time_saved_ns": int(round(saved)),
            "time_saving_ratio": time_saving_ratio,
            "estimated_local_ts_proxy": ts_proxy,
            "total_rd_loss": rd_loss,
            "mean_rd_loss": rd_loss / len(rows) if rows else 0.0,
            "estimated_rd_loss_proxy": rd_proxy,
            "estimated_efficiency_proxy": ts_proxy / rd_proxy if rd_proxy > 0 else None,
            "by_qp": {key: finalize_breakdown(value) for key, value in sorted(by_qp.items())},
            "by_size": {key: finalize_breakdown(value) for key, value in sorted(by_size.items())},
        }
    )
    return result


def serialize_thresholds(thresholds: Thresholds) -> list[dict[str, object]]:
    keys = sorted(set().union(*(table.keys() for table in thresholds.values())))
    return [
        {
            "actualCuQp": key[0],
            "W": key[1],
            "H": key[2],
            "energyCuts": list(thresholds["energy"].get(key, ())),
            "nnzCuts": list(thresholds["nnz"].get(key, ())),
            "lastCuts": list(thresholds["last"].get(key, ())),
        }
        for key in keys
    ]


def emit_cut_array(lines: list[str], name: str, field: str, thresholds: Thresholds, max_cuts: int) -> None:
    lines.append(
        f"struct LardLfnstSkip20{name.title()}Threshold "
        f"{{ int qp, width, height, count; double cut[{max_cuts}]; }};"
    )
    lines.append(f"static constexpr LardLfnstSkip20{name.title()}Threshold {field}[] = {{")
    for (qp, width, height), cuts in sorted(thresholds[name].items()):
        padded = list(cuts[:max_cuts]) + [0.0] * (max_cuts - len(cuts))
        cut_text = ", ".join(f"{value:.17g}" for value in padded)
        lines.append(f"  {{ {qp}, {width}, {height}, {min(len(cuts), max_cuts)}, {{ {cut_text} }} }},")
    lines.append("};")


def emit_inc(path: Path, thresholds: Thresholds, profile_tables: list[LevelTables], available: list[bool]) -> None:
    lines = [
        "// Generated by fit_lard_lfnst_skip20_direct.py. Do not edit.",
        "#define LARD_LFNST_SKIP20_TABLE_VERSION 2",
        f"static constexpr int LARD_LFNST_SKIP20_PROFILES = {len(profile_tables)};",
        "static constexpr int LARD_LFNST_SKIP20_ENERGY_CUTS = 3;",
        "static constexpr int LARD_LFNST_SKIP20_NNZ_CUTS = 2;",
        "static constexpr int LARD_LFNST_SKIP20_LAST_CUTS = 2;",
        "enum LardLfnstSkip20Level {",
    ]
    for name in LEVELS:
        lines.append(f"  LARD_LFNST_SKIP20_LEVEL_{name.upper()} = {LEVEL_IDS[name]},")
    lines += [
        f"  LARD_LFNST_SKIP20_LEVEL_COUNT = {len(LEVELS)}",
        "};",
        "static constexpr bool LARD_LFNST_SKIP20_PROFILE_AVAILABLE[] = { "
        + ", ".join("true" if value else "false" for value in available)
        + " };",
    ]
    emit_cut_array(lines, "energy", "LARD_LFNST_SKIP20_ENERGY_THRESHOLDS", thresholds, 3)
    emit_cut_array(lines, "nnz", "LARD_LFNST_SKIP20_NNZ_THRESHOLDS", thresholds, 2)
    emit_cut_array(lines, "last", "LARD_LFNST_SKIP20_LAST_THRESHOLDS", thresholds, 2)
    lines += [
        "struct LardLfnstSkip20MaskEntry {",
        "  int level, qp, width, height, modeGroup, setIdx, transpose, latBin, energyBin, nnzBin, lastBin;",
        "  unsigned char mask[LARD_LFNST_SKIP20_PROFILES];",
        "};",
        "static constexpr LardLfnstSkip20MaskEntry LARD_LFNST_SKIP20_DIRECT_MASKS[] = {",
    ]
    union_entries: set[tuple[int, Key]] = set()
    for tables in profile_tables:
        for level in LEVELS:
            union_entries.update((LEVEL_IDS[level], key) for key in tables[level])
    for level_id, key in sorted(union_entries):
        masks = []
        level = LEVELS[level_id]
        for tables in profile_tables:
            masks.append(tables[level].get(key, 0x7))
        lines.append(
            f"  {{ {level_id}, {', '.join(str(value) for value in key)}, "
            f"{{ {', '.join(str(mask) for mask in masks)} }} }},"
        )
    lines += ["};", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_numbers(text: str) -> list[float]:
    values = [float(item.strip()) for item in text.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("at least one value is required")
    return values


def fit_profiles(
    train_rows: list[Row],
    validation_rows: list[Row],
    thresholds: Thresholds,
    mus: list[float],
    min_samples: int,
    max_p95_relative_loss: float,
    anchor_time_ns: float | None = None,
    candidate_time_total_ns: float | None = None,
    intra_time_total_ns: float | None = None,
) -> tuple[list[LevelTables], list[dict[str, object]]]:
    tables_list: list[LevelTables] = []
    profiles: list[dict[str, object]] = []
    hierarchy_stats = build_hierarchy_stats(train_rows, thresholds, min_samples)
    for mu in mus:
        tables = train_hierarchy_from_stats(hierarchy_stats, mu, max_p95_relative_loss)
        tables_list.append(tables)
        profiles.append(
            {
                "mu": mu,
                "available": True,
                "table_entries": {level: len(tables[level]) for level in LEVELS},
                **replay(
                    validation_rows,
                    thresholds,
                    tables,
                    anchor_time_ns,
                    candidate_time_total_ns,
                    intra_time_total_ns,
                ),
            }
        )
    return tables_list, profiles


def pareto_indices(profiles: list[dict[str, object]]) -> list[int]:
    result: list[int] = []
    for idx, item in enumerate(profiles):
        ts = float(item["estimated_local_ts_proxy"])
        rd = float(item["estimated_rd_loss_proxy"])
        dominated = False
        for other_idx, other in enumerate(profiles):
            if other_idx == idx:
                continue
            other_ts = float(other["estimated_local_ts_proxy"])
            other_rd = float(other["estimated_rd_loss_proxy"])
            if other_ts >= ts and other_rd <= rd and (other_ts > ts or other_rd < rd):
                dominated = True
                break
        if not dominated:
            result.append(idx)
    return result


def select_target_profiles(
    candidate_tables: list[LevelTables],
    candidates: list[dict[str, object]],
    targets: list[float],
    min_efficiency: float,
    validation_rows: list[Row],
    thresholds: Thresholds,
    anchor_time_ns: float | None,
    candidate_time_total_ns: float | None,
    intra_time_total_ns: float | None,
) -> tuple[list[LevelTables], list[dict[str, object]], list[dict[str, object]]]:
    frontier = pareto_indices(candidates)
    selected_tables: list[LevelTables] = []
    selected_profiles: list[dict[str, object]] = []
    empty_tables: LevelTables = {level: {} for level in LEVELS}
    for target in targets:
        eligible: list[int] = []
        for idx in frontier:
            profile = candidates[idx]
            ts = float(profile["estimated_local_ts_proxy"])
            efficiency = profile["estimated_efficiency_proxy"]
            effective_efficiency = math.inf if efficiency is None else float(efficiency)
            if ts >= target and effective_efficiency >= min_efficiency:
                eligible.append(idx)
        if eligible:
            chosen = min(
                eligible,
                key=lambda idx: (
                    float(candidates[idx]["estimated_local_ts_proxy"]) - target,
                    float(candidates[idx]["estimated_rd_loss_proxy"]),
                ),
            )
            table = candidate_tables[chosen]
            profile = dict(candidates[chosen])
            profile["target_ts"] = target
            profile["available"] = True
            profile["source_candidate_index"] = chosen
        else:
            table = empty_tables
            profile = {
                "target_ts": target,
                "mu": None,
                "available": False,
                "source_candidate_index": None,
                "table_entries": {level: 0 for level in LEVELS},
                **replay(
                    validation_rows,
                    thresholds,
                    empty_tables,
                    anchor_time_ns,
                    candidate_time_total_ns,
                    intra_time_total_ns,
                ),
            }
        selected_tables.append(table)
        selected_profiles.append(profile)
    frontier_profiles = []
    for idx in frontier:
        item = dict(candidates[idx])
        item["source_candidate_index"] = idx
        frontier_profiles.append(item)
    return selected_tables, selected_profiles, frontier_profiles


def main() -> int:
    parser = argparse.ArgumentParser(description="Fit hierarchical time-weighted Skip20 direct mask tables.")
    parser.add_argument("logs", nargs="*", type=Path, help="legacy mode: use the same logs for train and replay")
    parser.add_argument("--train", nargs="+", type=Path)
    parser.add_argument("--validation", nargs="+", type=Path)
    parser.add_argument("--profiles", type=parse_numbers)
    parser.add_argument("--mu-grid", type=parse_numbers)
    parser.add_argument("--target-ts", type=parse_numbers, default=parse_numbers("3,5,6,7"))
    parser.add_argument("--anchor-time-ns", type=float)
    parser.add_argument("--candidate-time-total-ns", type=float)
    parser.add_argument("--intra-time-total-ns", type=float)
    parser.add_argument("--min-efficiency", type=float, default=10.0)
    parser.add_argument("--energy-bins", type=int, default=4)
    parser.add_argument("--nnz-bins", type=int, default=3)
    parser.add_argument("--last-bins", type=int, default=3)
    parser.add_argument("--key-profile", choices=("fine", "no-mode", "core"), default="fine")
    parser.add_argument("--min-samples", type=int, default=200)
    parser.add_argument("--max-p95-relative-loss", type=float, default=1.0)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-inc", type=Path)
    args = parser.parse_args()

    if args.train:
        if not args.validation:
            parser.error("--validation is required with --train")
        train_paths = args.train
        validation_paths = args.validation
        v2_mode = True
    elif args.logs:
        train_paths = args.logs
        validation_paths = args.logs
        v2_mode = False
    else:
        parser.error("provide legacy logs or --train and --validation")

    try:
        train_rows = load_rows(train_paths)
        validation_rows = load_rows(validation_paths)
    except ValueError as exc:
        parser.error(str(exc))
    if not train_rows:
        parser.error("no complete training rows")
    if not validation_rows:
        parser.error("no complete validation rows")

    thresholds = build_thresholds(train_rows, args.energy_bins, args.nnz_bins, args.last_bins)
    explicit_profiles = args.profiles is not None
    if explicit_profiles:
        mus = args.profiles
    elif args.mu_grid is not None:
        mus = args.mu_grid
    elif v2_mode:
        mus = [0.0, *[float(value) for value in np.logspace(-3, 6, 73)]]
    else:
        mus = [3000.0, 300.0, 30.0, 3.0]
    candidate_tables, candidates = fit_profiles(
        train_rows,
        validation_rows,
        thresholds,
        mus,
        args.min_samples,
        args.max_p95_relative_loss,
        args.anchor_time_ns,
        args.candidate_time_total_ns,
        args.intra_time_total_ns,
    )
    if v2_mode and not explicit_profiles:
        profile_tables, profiles, frontier_profiles = select_target_profiles(
            candidate_tables,
            candidates,
            args.target_ts,
            args.min_efficiency,
            validation_rows,
            thresholds,
            args.anchor_time_ns,
            args.candidate_time_total_ns,
            args.intra_time_total_ns,
        )
    else:
        profile_tables = candidate_tables
        profiles = candidates
        frontier_profiles = [dict(item, source_candidate_index=idx) for idx, item in enumerate(candidates)]
    available = [bool(profile["available"]) for profile in profiles]

    result = {
        "version": 2 if v2_mode else 1,
        "rows": len(train_rows),
        "split": {
            "train_rows": len(train_rows),
            "validation_rows": len(validation_rows),
            "train_logs": [str(path) for path in train_paths],
            "validation_logs": [str(path) for path in validation_paths],
        },
        "min_samples": args.min_samples,
        "max_p95_relative_loss": args.max_p95_relative_loss,
        "target_ts": args.target_ts,
        "anchor_time_ns": args.anchor_time_ns,
        "candidate_time_total_ns": args.candidate_time_total_ns,
        "intra_time_total_ns": args.intra_time_total_ns,
        "min_efficiency": args.min_efficiency,
        "fallback_order": list(LEVELS),
        "bin_thresholds": serialize_thresholds(thresholds),
        # Kept for consumers of the Skip20-v1 report schema.
        "energy_thresholds": [
            {
                "actualCuQp": item["actualCuQp"],
                "W": item["W"],
                "H": item["H"],
                "cuts": item["energyCuts"],
            }
            for item in serialize_thresholds(thresholds)
        ],
        "profiles": profiles,
        "pareto_candidates": frontier_profiles,
        "input_logs": [str(path) for path in train_paths],
    }
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if args.out_inc:
        emit_inc(args.out_inc, thresholds, profile_tables, available)
    if not args.out_json:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
