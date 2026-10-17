#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


MASK_NAME = {
    0x1: "{0}",
    0x3: "{0,1}",
    0x5: "{0,2}",
    0x7: "{0,1,2}",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize LardLfnstSkip=10 decision statistics CSV.")
    parser.add_argument("csv_file", type=Path)
    args = parser.parse_args()

    by_qp: dict[int, Counter[str]] = defaultdict(Counter)
    total = Counter()
    with args.csv_file.open("r", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            qp = int(row["qp"])
            mask = int(row["mask"])
            raw_mask = int(row["rawMask"])
            key = MASK_NAME.get(mask, str(mask))
            raw_key = "raw_" + MASK_NAME.get(raw_mask, str(raw_mask))
            by_qp[qp][key] += 1
            by_qp[qp][raw_key] += 1
            by_qp[qp]["safeGate"] += int(row["safeGate"])
            by_qp[qp]["total"] += 1
            total[key] += 1
            total[raw_key] += 1
            total["safeGate"] += int(row["safeGate"])
            total["total"] += 1

    fieldnames = [
        "qp",
        "total",
        "{0}_pct",
        "{0,1}_pct",
        "{0,2}_pct",
        "{0,1,2}_pct",
        "safeGate_pct",
        "raw_{0}_pct",
        "raw_{0,1}_pct",
        "raw_{0,2}_pct",
        "raw_{0,1,2}_pct",
    ]
    writer = csv.DictWriter(__import__("sys").stdout, fieldnames=fieldnames)
    writer.writeheader()

    for qp, counter in sorted(by_qp.items()):
        denom = max(1, counter["total"])
        out = {"qp": qp, "total": counter["total"]}
        for key in ("{0}", "{0,1}", "{0,2}", "{0,1,2}", "safeGate", "raw_{0}", "raw_{0,1}", "raw_{0,2}", "raw_{0,1,2}"):
            out[f"{key}_pct"] = counter[key] / denom * 100.0
        writer.writerow(out)

    if total["total"]:
        denom = total["total"]
        out = {"qp": "all", "total": total["total"]}
        for key in ("{0}", "{0,1}", "{0,2}", "{0,1,2}", "safeGate", "raw_{0}", "raw_{0,1}", "raw_{0,2}", "raw_{0,1,2}"):
            out[f"{key}_pct"] = total[key] / denom * 100.0
        writer.writerow(out)


if __name__ == "__main__":
    main()
