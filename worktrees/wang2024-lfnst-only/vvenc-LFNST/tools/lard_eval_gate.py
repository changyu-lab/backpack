#!/usr/bin/env python3
"""Check LARD-LFNST experiment summaries against TS/BDBR gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def pick_ts(data: dict) -> float:
    for key in ("TS_median_pct", "TS_pct"):
        if key in data:
            return float(data[key])
    raise KeyError("summary does not contain TS_median_pct or TS_pct")


def pick_max_yuv_bdbr(data: dict) -> float:
    if "MaxYuvBDBR_pct" in data:
        return float(data["MaxYuvBDBR_pct"])
    if "MedianMaxYuvBDBR_pct" in data:
        return float(data["MedianMaxYuvBDBR_pct"])
    keys = ("WS_YUV_BDBR_pct", "S_YUV_BDBR_pct", "CPP_YUV_BDBR_pct")
    missing = [k for k in keys if k not in data]
    if missing:
        raise KeyError(f"summary missing BDBR keys: {', '.join(missing)}")
    return max(float(data[k]) for k in keys)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("summary", type=Path)
    ap.add_argument("--max-yuv-bdbr", type=float, default=0.5)
    ap.add_argument("--min-ts", type=float, default=10.0)
    args = ap.parse_args()

    data = load_json(args.summary)
    ts = pick_ts(data)
    max_bdbr = pick_max_yuv_bdbr(data)
    ok_bdbr = max_bdbr < args.max_yuv_bdbr
    ok_ts = ts >= args.min_ts
    out = {
        "summary": str(args.summary),
        "TS_pct": ts,
        "MaxYuvBDBR_pct": max_bdbr,
        "max_yuv_bdbr_gate": args.max_yuv_bdbr,
        "min_ts_gate": args.min_ts,
        "pass": ok_bdbr and ok_ts,
        "bdbr_pass": ok_bdbr,
        "ts_pass": ok_ts,
    }
    print(json.dumps(out, indent=2))
    raise SystemExit(0 if out["pass"] else 1)


if __name__ == "__main__":
    main()
