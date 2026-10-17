#!/usr/bin/env python3
"""Verify VVenC LFNST input ordering and integer response from Skip15 CSV logs."""
from __future__ import annotations

import argparse
import csv
import glob
import json
import sys
from pathlib import Path

import numpy as np


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from compute_lfnst_theory_stats import parse_rom_lfnst
from lard_lfnst.generate_lard_lfnst_cov_table import lfnst_positions


def resolve_logs(patterns: list[str]) -> list[Path]:
    paths = []
    for pattern in patterns:
        matched = [Path(path) for path in glob.glob(pattern)]
        paths.extend(matched or ([Path(pattern)] if Path(pattern).exists() else []))
    return sorted(set(paths))


def read_rows(paths: list[Path]) -> list[dict[str, str]]:
    rows = []
    for path in paths:
        with path.open(newline="", encoding="utf-8") as handle:
            rows.extend(csv.DictReader(handle))
    return rows


def integer_response(matrix: np.ndarray, values: list[int], out_n: int, k_in: int) -> list[int]:
    raw = np.rint(matrix[:out_n, :k_in] * 128.0).astype(np.int64)
    vector = np.asarray(values[:k_in], dtype=np.int64)
    return [int((int(value) + 64) // 128) for value in raw @ vector]


def extract_input_from_raw(raw: list[int], k_in: int, transpose: bool) -> list[int]:
    sb_size = 8 if k_in == 48 else 4
    normal_positions = lfnst_positions(sb_size, sb_size, sb_size, False)
    target_positions = lfnst_positions(sb_size, sb_size, sb_size, transpose)
    values = {position: value for position, value in zip(normal_positions, raw[:k_in])}
    return [values[position] for position in target_positions]


def verify(rows: list[dict[str, str]], rom_lfnst: Path, require_coverage: bool) -> dict[str, object]:
    lfnst8, lfnst4, _, _ = parse_rom_lfnst(rom_lfnst)
    checked = 0
    input_mismatches = 0
    output_mismatches = 0
    coverage = {"kIn": set(), "transpose": set(), "candidate": set(), "setIdx": set()}
    examples = []
    for row_index, row in enumerate(rows):
        if int(row.get("tableFound", "1")) == 0:
            continue
        k_in = int(row["kIn"])
        out_n = int(row["outN"])
        set_idx = int(row["setIdx"])
        transpose = int(row["transpose"])
        source = lfnst8 if k_in == 48 else lfnst4
        for candidate in (1, 2):
            if int(row.get(f"actualValid{candidate}", "1")) == 0:
                continue
            actual_input = [int(row[f"actualX{candidate}_{i:02d}"]) for i in range(k_in)]
            actual_raw = [int(row[f"actualRaw{candidate}_{i:02d}"]) for i in range(k_in)]
            extracted_input = extract_input_from_raw(actual_raw, k_in, bool(transpose))
            actual_output = [int(row[f"actualY{candidate}_{i:02d}"]) for i in range(out_n)]
            predicted_output = integer_response(source[set_idx, candidate - 1], actual_input, out_n, k_in)
            bad_input = [index for index, (left, right) in enumerate(zip(extracted_input, actual_input)) if left != right]
            bad_output = [index for index, (left, right) in enumerate(zip(predicted_output, actual_output)) if left != right]
            input_mismatches += len(bad_input)
            output_mismatches += len(bad_output)
            if (bad_input or bad_output) and len(examples) < 10:
                examples.append(
                    {
                        "row": row_index,
                        "candidate": candidate,
                        "input_indices": bad_input[:8],
                        "output_indices": bad_output[:8],
                    }
                )
            checked += 1
            coverage["kIn"].add(k_in)
            coverage["transpose"].add(transpose)
            coverage["candidate"].add(candidate)
            coverage["setIdx"].add(set_idx)

    coverage_json = {key: sorted(values) for key, values in coverage.items()}
    required = (
        coverage["kIn"] == {16, 48}
        and coverage["transpose"] == {0, 1}
        and coverage["candidate"] == {1, 2}
        and len(coverage["setIdx"]) >= 2
    )
    result = {
        "rows": len(rows),
        "responses_checked": checked,
        "input_mismatches": input_mismatches,
        "output_mismatches": output_mismatches,
        "coverage": coverage_json,
        "coverage_complete": required,
        "examples": examples,
    }
    if input_mismatches or output_mismatches or (require_coverage and not required):
        raise AssertionError(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("logs", nargs="+", help="CSV paths or glob patterns")
    parser.add_argument("--rom-lfnst", type=Path, default=Path("source/Lib/CommonLib/Rom.cpp"))
    parser.add_argument("--require-coverage", action="store_true")
    parser.add_argument("--out-json", type=Path)
    args = parser.parse_args()
    paths = resolve_logs(args.logs)
    if not paths:
        raise SystemExit("no input logs found")
    result = verify(read_rows(paths), args.rom_lfnst, args.require_coverage)
    result["input_logs"] = [str(path) for path in paths]
    text = json.dumps(result, indent=2) + "\n"
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
