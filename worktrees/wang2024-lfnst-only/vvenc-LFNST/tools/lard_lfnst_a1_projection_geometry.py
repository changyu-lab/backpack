#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


EPS = 1e-12
LAT_BUCKETS = ((0.0, 30.0, "[0,30)"), (30.0, 60.0, "[30,60)"), (60.0, 75.0, "[60,75)"), (75.0, 90.000001, "[75,90]"))


@dataclass
class EnergyAcc:
    samples: int = 0
    energy: np.ndarray = field(default_factory=lambda: np.zeros(64, dtype=np.float64))

    def add(self, vec: np.ndarray) -> None:
        self.samples += 1
        self.energy += vec


def parse_case(path: Path) -> tuple[str, float, int]:
    m = re.search(r"(train|validation)_s([0-9p.]+)_qp(\d+)$", path.stem, flags=re.IGNORECASE)
    if not m:
        raise RuntimeError(f"trace filename must look like train_s1p15_qp32.csv: {path}")
    return m.group(1).lower(), float(m.group(2).replace("p", ".")), int(m.group(3))


def load_manifests(manifest_dir: Path) -> dict[str, dict[int, dict[str, str]]]:
    out: dict[str, dict[int, dict[str, str]]] = {}
    for split in ("train", "validation"):
        path = manifest_dir / f"sjtu_{split}_patch256_manifest.csv"
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as fh:
            out[split] = {int(r["patchIndex"]): r for r in csv.DictReader(fh)}
    return out


def patch_index_for_block(row: dict[str, str], patch: int = 128) -> int:
    poc = int(row["poc"])
    x_center = int(row["x"]) + 0.5 * int(row["w"])
    y_center = int(row["y"]) + 0.5 * int(row["h"])
    tile_x = min(3, max(0, int(x_center // patch)))
    tile_y = min(3, max(0, int(y_center // patch)))
    return poc * 16 + tile_y * 4 + tile_x


def lat_bucket(lat: float) -> str:
    for lo, hi, name in LAT_BUCKETS:
        if lo <= lat < hi:
            return name
    return "[75,90]"


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
    return "area_long" if mx >= 4 * mn else "area_large"


def mode_group(mode: int) -> str:
    if mode == 0:
        return "g0_planar"
    if mode == 1:
        return "g1_dc"
    if mode <= 17:
        return "g2_ang_2_17"
    if mode <= 34:
        return "g3_ang_18_34"
    if mode <= 50:
        return "g4_ang_35_50"
    return "g5_ang_51_plus"


def active_mask(spec_side: int) -> np.ndarray:
    mask = np.zeros(64, dtype=bool)
    if spec_side == 4:
        for v in range(4):
            for u in range(4):
                mask[v * 8 + u] = True
    else:
        for v in range(8):
            for u in range(8):
                if not (u >= 4 and v >= 4):
                    mask[v * 8 + u] = True
    return mask


def normalize(acc: EnergyAcc, mask: np.ndarray) -> np.ndarray:
    e = np.maximum(acc.energy.copy(), 0.0)
    e[~mask] = 0.0
    total = float(e.sum())
    return e / (total + EPS)


def entropy(p: np.ndarray, mask: np.ndarray) -> float:
    q = p[mask]
    return float(-np.sum(q * np.log(q + EPS)))


def direction_imbalance(p: np.ndarray, mask: np.ndarray) -> tuple[float, float, float]:
    mx = 0.0
    my = 0.0
    for v in range(8):
        for u in range(8):
            idx = v * 8 + u
            if not mask[idx]:
                continue
            mx += (u * u) * float(p[idx])
            my += (v * v) * float(p[idx])
    return float((my - mx) / (my + mx + EPS)), float(mx), float(my)


def js_divergence(p: np.ndarray, q: np.ndarray, mask: np.ndarray) -> float:
    pp = p[mask]
    qq = q[mask]
    m = 0.5 * (pp + qq)
    kl_pm = float(np.sum(pp * (np.log(pp + EPS) - np.log(m + EPS))))
    kl_qm = float(np.sum(qq * (np.log(qq + EPS) - np.log(m + EPS))))
    return 0.5 * (kl_pm + kl_qm)


def trace_files(run_root: Path) -> list[Path]:
    trace_dir = run_root / "traces" if (run_root / "traces").is_dir() else run_root
    return sorted(p for p in trace_dir.glob("*_s*_qp*.csv") if not p.name.endswith(".final.csv") and p.stat().st_size > 0)


def analyze(run_root: Path, manifest_dir: Path, out_dir: Path, max_rows_per_trace: int | None) -> dict[str, int]:
    manifests = load_manifests(manifest_dir)
    acc: dict[tuple[str, float, int, str, str, str, int], EnergyAcc] = defaultdict(EnergyAcc)
    rows_seen = used = 0
    spec_cols = [f"spec{i:02d}" for i in range(64)]

    for trace in trace_files(run_root):
        split, stretch, qp = parse_case(trace)
        manifest = manifests.get(split)
        if manifest is None:
            raise RuntimeError(f"missing manifest for split {split}")
        with trace.open(newline="", encoding="utf-8", errors="ignore") as fh:
            reader = csv.DictReader(fh)
            local_rows = 0
            for row in reader:
                rows_seen += 1
                local_rows += 1
                if max_rows_per_trace is not None and local_rows > max_rows_per_trace:
                    break
                if row.get("lfnstIdx") != "0" or row.get("mtsIdx") != "0" or not row.get("spec00"):
                    continue
                try:
                    pidx = patch_index_for_block(row)
                    man = manifest[pidx]
                    spec_side = int(row.get("specSide") or 8)
                    vec = np.asarray([float(row.get(c) or 0.0) for c in spec_cols], dtype=np.float64)
                    lat = float(man.get("absLatitudeDeg", man.get("sourceLatitudeDeg", "nan")))
                    key = (
                        split,
                        stretch,
                        qp,
                        lat_bucket(abs(lat)),
                        size_group(int(row["w"]), int(row["h"])),
                        mode_group(int(row["intraMode"])),
                        spec_side,
                    )
                except (KeyError, ValueError):
                    continue
                acc[key].add(vec)
                used += 1

    dist_rows: list[dict[str, object]] = []
    p_by_key: dict[tuple[str, float, int, str, str, str, int], np.ndarray] = {}
    mask_by_key: dict[tuple[str, float, int, str, str, str, int], np.ndarray] = {}
    for key, a in sorted(acc.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2], kv[0][3], kv[0][4], kv[0][5], kv[0][6])):
        split, stretch, qp, bucket, bsize, mgroup, spec_side = key
        mask = active_mask(spec_side)
        p = normalize(a, mask)
        adir, mx, my = direction_imbalance(p, mask)
        p_by_key[key] = p
        mask_by_key[key] = mask
        dist_rows.append(
            {
                "Split": split,
                "StretchS": stretch,
                "QP": qp,
                "LatitudeBucket": bucket,
                "BlockSizeGroup": bsize,
                "ModeGroup": mgroup,
                "SpecSide": spec_side,
                "Samples": a.samples,
                "H0": entropy(p, mask),
                "A_dir": adir,
                "M_x": mx,
                "M_y": my,
            }
        )
        for idx in range(64):
            if mask[idx]:
                dist_rows[-1][f"p{idx:02d}"] = float(p[idx])

    for row in dist_rows:
        key = (
            str(row["Split"]),
            float(row["StretchS"]),
            int(row["QP"]),
            str(row["LatitudeBucket"]),
            str(row["BlockSizeGroup"]),
            str(row["ModeGroup"]),
            int(row["SpecSide"]),
        )
        low_key = (key[0], key[1], key[2], "[0,30)", key[4], key[5], key[6])
        if key[3] == "[0,30)" or low_key not in p_by_key:
            row["D_JS_to_lowlat"] = 0.0 if key[3] == "[0,30)" else math.nan
        else:
            row["D_JS_to_lowlat"] = js_divergence(p_by_key[key], p_by_key[low_key], mask_by_key[key])

    out_dir.mkdir(parents=True, exist_ok=True)
    base_cols = ["Split", "StretchS", "QP", "LatitudeBucket", "BlockSizeGroup", "ModeGroup", "SpecSide", "Samples", "H0", "A_dir", "M_x", "M_y", "D_JS_to_lowlat"]
    p_cols = [f"p{i:02d}" for i in range(64)]
    with (out_dir / "table_A1_lowfreq_distribution.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=base_cols + p_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(dist_rows)

    summary_keys = ["Split", "StretchS", "QP", "LatitudeBucket", "BlockSizeGroup"]
    summary: dict[tuple[object, ...], dict[str, float]] = {}
    for row in dist_rows:
        key = tuple(row[k] for k in summary_keys)
        samples = float(row["Samples"])
        dst = summary.setdefault(key, {"Samples": 0.0, "H0": 0.0, "A_dir": 0.0, "D_JS_to_lowlat": 0.0, "D_JS_samples": 0.0})
        dst["Samples"] += samples
        dst["H0"] += float(row["H0"]) * samples
        dst["A_dir"] += float(row["A_dir"]) * samples
        djs = float(row["D_JS_to_lowlat"])
        if math.isfinite(djs):
            dst["D_JS_to_lowlat"] += djs * samples
            dst["D_JS_samples"] += samples

    with (out_dir / "table_A1_summary_by_lat_size.csv").open("w", newline="", encoding="utf-8") as fh:
        cols = summary_keys + ["Samples", "Mean_H0", "Mean_A_dir", "Mean_D_JS_to_lowlat"]
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for key, val in sorted(summary.items(), key=lambda kv: (kv[0][0], float(kv[0][1]), int(kv[0][2]), kv[0][3], kv[0][4])):
            samples = val["Samples"]
            djs_samples = val["D_JS_samples"]
            writer.writerow(
                {
                    **dict(zip(summary_keys, key)),
                    "Samples": int(samples),
                    "Mean_H0": val["H0"] / samples if samples > 0 else math.nan,
                    "Mean_A_dir": val["A_dir"] / samples if samples > 0 else math.nan,
                    "Mean_D_JS_to_lowlat": val["D_JS_to_lowlat"] / djs_samples if djs_samples > 0 else math.nan,
                }
            )

    report = [
        "# Experiment A1 Projection Geometry Low-Frequency Redistribution",
        "",
        f"Trace files: `{len(trace_files(run_root))}`",
        f"Rows scanned: `{rows_seen}`",
        f"No-LFNST primary spectrum rows used: `{used}`",
        f"Distribution groups: `{len(dist_rows)}`",
        "",
        "Metrics are computed from `spec00..spec63`, which already stores squared DCT-like residual coefficient energy for the no-LFNST primary transform.",
        "`D_JS_to_lowlat` compares each latitude bucket with `[0,30)` under the same split, stretch factor, QP, block-size group, mode group, and `specSide`.",
    ]
    (out_dir / "A1_projection_geometry_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return {"trace_files": len(trace_files(run_root)), "rows_seen": rows_seen, "used": used, "groups": len(dist_rows)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-root", type=Path, required=True)
    ap.add_argument("--manifest-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--max-rows-per-trace", type=int)
    args = ap.parse_args()
    print(analyze(args.run_root, args.manifest_dir, args.out_dir, args.max_rows_per_trace))


if __name__ == "__main__":
    main()
