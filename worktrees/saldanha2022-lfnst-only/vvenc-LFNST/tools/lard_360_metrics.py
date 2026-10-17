#!/usr/bin/env python3
"""Compute ERP WS-PSNR, S-PSNR-NN and CPP-PSNR curves for YUV420 test runs.

The WS weights, S-PSNR-NN sphere samples and CPP valid-domain equations follow
the 360Lib ERP metric implementation closely enough for encoder sweeps.  CPP
sampling is applied directly to the reconstruction error plane with bilinear
interpolation.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path

try:
    import numpy as np
except ModuleNotFoundError:
    np = None


MAXVAL = 255.0
_WS_WEIGHT_CACHE: dict[tuple[int, int, int, bool], np.ndarray] = {}
_CPP_TABLE_CACHE: dict[tuple[int, int], tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}


def read_yuv420_frame(
    path: Path,
    width: int,
    height: int,
    frame_idx: int = 0,
    bitdepth: int = 8,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    bytes_per_sample = 1 if bitdepth <= 8 else 2
    frame_size = width * height * 3 // 2 * bytes_per_sample
    offset = frame_size * frame_idx
    with path.open("rb") as fh:
        fh.seek(offset)
        raw = fh.read(frame_size)
    dtype = np.uint8 if bitdepth <= 8 else np.dtype("<u2")
    data = np.frombuffer(raw, dtype=dtype)
    expected_samples = width * height * 3 // 2
    if data.size != expected_samples:
        raise RuntimeError(f"short YUV frame in {path}: got {data.size}, expected {expected_samples}")
    y_size = width * height
    c_width = width // 2
    c_height = height // 2
    y = data[:y_size].reshape(height, width)
    u = data[y_size : y_size + c_width * c_height].reshape(c_height, c_width)
    v = data[y_size + c_width * c_height :].reshape(c_height, c_width)
    return y, u, v


def erp_ws_mse(diff: np.ndarray, luma_height: int, chroma: bool) -> float:
    h, w = diff.shape
    key = (w, h, luma_height, chroma)
    weights = _WS_WEIGHT_CACHE.get(key)
    if weights is None and chroma:
        # 360Lib default ChromaSampleLocType=2: vertical chroma offset is 0.
        ys = np.arange(h, dtype=np.float64)
        weights = np.cos(((ys * 2.0) + 0.5 - luma_height / 2.0) * math.pi / luma_height)
    elif weights is None:
        ys = np.arange(h, dtype=np.float64)
        weights = np.cos((ys - (h / 2.0 - 0.5)) * math.pi / h)
    if key not in _WS_WEIGHT_CACHE:
        weights = weights / weights.sum() / w
        _WS_WEIGHT_CACHE[key] = weights
    return float(((diff.astype(np.float64) ** 2) * weights[:, None]).sum())


def bilinear_sample_periodic_x(img: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    h, w = img.shape
    xs = np.mod(xs, w)
    ys = np.clip(ys, 0.0, h - 1.0)
    x0 = np.floor(xs).astype(np.int64)
    y0 = np.floor(ys).astype(np.int64)
    x1 = (x0 + 1) % w
    y1 = np.minimum(y0 + 1, h - 1)
    wx = xs - x0
    wy = ys - y0
    imgf = img.astype(np.float64)
    top = imgf[y0, x0] * (1.0 - wx) + imgf[y0, x1] * wx
    bot = imgf[y1, x0] * (1.0 - wx) + imgf[y1, x1] * wx
    return top * (1.0 - wy) + bot * wy


def cpp_mse_from_error(err: np.ndarray) -> float:
    table = cpp_sample_table(err.shape[1], err.shape[0])
    return cpp_mse_from_error_table(err, table)


def cpp_sample_table(
    width: int,
    height: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    key = (width, height)
    cached = _CPP_TABLE_CACHE.get(key)
    if cached is not None:
        return cached

    xs = np.arange(width, dtype=np.float64)
    x_cpp = (xs / width) * (2.0 * math.pi) - math.pi
    x_coords: list[np.ndarray] = []
    y_coords: list[np.ndarray] = []
    for y in range(height):
        y_cpp = (y / height) * math.pi - (math.pi / 2.0)
        phi = 3.0 * math.asin(max(-1.0, min(1.0, y_cpp / math.pi)))
        denom = 2.0 * math.cos(2.0 * phi / 3.0) - 1.0
        lam = x_cpp / denom
        erp_x = (lam + math.pi) / (2.0 * math.pi) * width
        erp_y = (phi + math.pi / 2.0) / math.pi * height
        idx_x = np.where(erp_x < 0.0, erp_x - 0.5, erp_x + 0.5).astype(np.int64)
        idx_y = int(erp_y - 0.5) if erp_y < 0.0 else int(erp_y + 0.5)
        mask = (idx_x >= 0) & (idx_x < width) & (idx_y >= 0) & (idx_y < height)
        if np.any(mask):
            x_coords.append(erp_x[mask])
            y_coords.append(np.full(mask.sum(), erp_y, dtype=np.float64))
    if not x_coords:
        raise RuntimeError("CPP valid sample count is zero")

    sample_x = np.mod(np.concatenate(x_coords), width)
    sample_y = np.clip(np.concatenate(y_coords), 0.0, height - 1.0)
    x0 = np.mod(np.floor(sample_x).astype(np.int64), width).astype(np.int32)
    y0 = np.clip(np.floor(sample_y).astype(np.int64), 0, height - 1).astype(np.int32)
    x1 = ((x0 + 1) % width).astype(np.int32)
    y1 = np.minimum(y0 + 1, height - 1).astype(np.int32)
    wx = sample_x - x0
    wy = sample_y - y0
    table = (x0, y0, x1, y1, wx, wy)
    _CPP_TABLE_CACHE[key] = table
    return table


def cpp_mse_from_error_table(
    err: np.ndarray,
    table: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> float:
    x0, y0, x1, y1, wx, wy = table
    img = err.astype(np.float64)
    top = img[y0, x0] * (1.0 - wx) + img[y0, x1] * wx
    bot = img[y1, x0] * (1.0 - wx) + img[y1, x1] * wx
    vals = top * (1.0 - wy) + bot * wy
    return float(np.mean(vals * vals))


def cpp_mse_from_error_reference(err: np.ndarray) -> float:
    h, w = err.shape
    xs = np.arange(w, dtype=np.float64)
    x_cpp = (xs / w) * (2.0 * math.pi) - math.pi
    total = 0.0
    count = 0
    for y in range(h):
        y_cpp = (y / h) * math.pi - (math.pi / 2.0)
        phi = 3.0 * math.asin(max(-1.0, min(1.0, y_cpp / math.pi)))
        denom = 2.0 * math.cos(2.0 * phi / 3.0) - 1.0
        lam = x_cpp / denom
        erp_x = (lam + math.pi) / (2.0 * math.pi) * w
        erp_y = (phi + math.pi / 2.0) / math.pi * h
        idx_x = np.where(erp_x < 0.0, erp_x - 0.5, erp_x + 0.5).astype(np.int64)
        idx_y = int(erp_y - 0.5) if erp_y < 0.0 else int(erp_y + 0.5)
        mask = (idx_x >= 0) & (idx_x < w) & (idx_y >= 0) & (idx_y < h)
        if np.any(mask):
            vals = bilinear_sample_periodic_x(err, erp_x[mask], np.full(mask.sum(), erp_y))
            total += float(np.dot(vals, vals))
            count += int(mask.sum())
    if count == 0:
        raise RuntimeError("CPP valid sample count is zero")
    return total / count


def psnr_from_mse(mse: float, maxval: float = MAXVAL) -> float:
    return 999.99 if mse <= 0.0 else 10.0 * math.log10((maxval * maxval) / mse)


def yuv_psnr(y: float, u: float, v: float) -> float:
    my = (MAXVAL * MAXVAL) / (10.0 ** (y / 10.0))
    mu = (MAXVAL * MAXVAL) / (10.0 ** (u / 10.0))
    mv = (MAXVAL * MAXVAL) / (10.0 ** (v / 10.0))
    return psnr_from_mse((4.0 * my + mu + mv) / 6.0)


def yuv_psnr_from_mse(y_mse: float, u_mse: float, v_mse: float, maxval: float = MAXVAL) -> float:
    return psnr_from_mse((4.0 * y_mse + u_mse + v_mse) / 6.0, maxval)


def load_sphere_points(path: Path) -> tuple[np.ndarray, np.ndarray]:
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        first = fh.readline().strip()
        n = int(first)
        lat = np.empty(n, dtype=np.float64)
        lon = np.empty(n, dtype=np.float64)
        for i in range(n):
            line = fh.readline()
            if not line:
                raise RuntimeError(f"short sphere point file {path}: got {i}, expected {n}")
            a, b = line.split()[:2]
            lat[i] = float(a)
            lon[i] = float(b)
    return lat, lon


def erp_spsnr_nn_indices(
    sphere_file: Path,
    width: int,
    height: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    lat_deg, lon_deg = load_sphere_points(sphere_file)
    lat = np.deg2rad(lat_deg)
    lon = np.deg2rad(lon_deg)

    # Match 360Lib TSPSNRMetric for ERP: sphere lat/lon -> cartesian -> TEquiRect::map3DTo2D -> round -> clamp.
    x3 = np.sin(lon) * np.cos(lat)
    y3 = np.sin(lat)
    z3 = -np.cos(lon) * np.cos(lat)
    yaw = np.arctan2(z3, x3)
    len3 = np.sqrt(x3 * x3 + y3 * y3 + z3 * z3)
    xpos = (math.pi - yaw) * width / (2.0 * math.pi) - 0.5
    ypos = np.arccos(np.clip(y3 / np.maximum(len3, 1.0e-12), -1.0, 1.0)) * height / math.pi - 0.5

    xi = np.rint(xpos).astype(np.int64)
    yi = np.rint(ypos).astype(np.int64)
    xi = np.clip(xi, 0, width - 1)
    yi = np.clip(yi, 0, height - 1)

    # For 4:2:0 ERP, 360Lib either uses a chroma-specific table or falls back to luma index shifts.
    # The shifted-nearest rule is the stable path for our ERP YUV420 sweeps.
    xic = np.clip(xi >> 1, 0, width // 2 - 1)
    yic = np.clip(yi >> 1, 0, height // 2 - 1)
    return xi.astype(np.int32), yi.astype(np.int32), xic.astype(np.int32), yic.astype(np.int32)


def spsnr_nn_mse(diff: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> float:
    vals = diff[ys, xs].astype(np.float64)
    return float(np.mean(vals * vals))


def parse_log(path: Path) -> tuple[float, float, float, float, float]:
    data = path.read_bytes()
    text = data.decode("utf-16") if data.startswith((b"\xff\xfe", b"\xfe\xff")) else data.decode("utf-8", errors="ignore")
    vals = None
    for line in text.splitlines():
        if "YUV-PSNR" in line or "Total Frames" in line:
            continue
        if "vvenc [info]:" in line and re.search(r"\s+a\s+", line):
            nums = re.findall(r"[-+]?\d+(?:\.\d+)?", line.split("]:", 1)[-1])
            if len(nums) >= 6:
                vals = list(map(float, nums[-6:]))
    if vals is None:
        raise RuntimeError(f"could not parse RD line from {path}")
    return vals[1], vals[2], vals[3], vals[4], vals[5]


def polyfit3(x: list[float], y: list[float]) -> list[float]:
    if np is None:
        if len(x) != 4 or len(y) != 4:
            raise RuntimeError("numpy is required for non-4-point polynomial fitting")
        matrix = [[float(xi) ** 3, float(xi) ** 2, float(xi), 1.0, float(yi)] for xi, yi in zip(x, y)]
        for col in range(4):
            pivot = max(range(col, 4), key=lambda row: abs(matrix[row][col]))
            if abs(matrix[pivot][col]) < 1.0e-12:
                raise RuntimeError("singular BD-rate polynomial fit")
            matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
            scale = matrix[col][col]
            matrix[col] = [value / scale for value in matrix[col]]
            for row in range(4):
                if row == col:
                    continue
                factor = matrix[row][col]
                matrix[row] = [value - factor * base for value, base in zip(matrix[row], matrix[col])]
        return [matrix[row][4] for row in range(4)]
    return np.polyfit(np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64), 3).tolist()


def polyint(coeff: list[float], lo: float, hi: float) -> float:
    if np is None:
        degree = len(coeff) - 1
        total = 0.0
        for idx, value in enumerate(coeff):
            power = degree - idx + 1
            total += float(value) / power * (hi ** power - lo ** power)
        return total
    p = np.poly1d(coeff)
    q = np.polyint(p)
    return float(q(hi) - q(lo))


def bdrate(anchor_rates: list[float], anchor_psnr: list[float], test_rates: list[float], test_psnr: list[float]) -> float:
    a = sorted(zip(anchor_psnr, anchor_rates))
    t = sorted(zip(test_psnr, test_rates))
    xa = [p for p, _ in a]
    xt = [p for p, _ in t]
    ya = [math.log(r) for _, r in a]
    yt = [math.log(r) for _, r in t]
    lo = max(min(xa), min(xt))
    hi = min(max(xa), max(xt))
    if hi <= lo:
        return float("nan")
    ca = polyfit3(xa, ya)
    ct = polyfit3(xt, yt)
    avg = (polyint(ct, lo, hi) - polyint(ca, lo, hi)) / (hi - lo)
    return (math.exp(avg) - 1.0) * 100.0


def compute_case_with_bitdepth(
    orig: Path | tuple[np.ndarray, np.ndarray, np.ndarray],
    rec_path: Path,
    width: int,
    height: int,
    rec_bitdepth: int,
    orig_bitdepth: int,
    spsnr_table: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None = None,
    frames: int = 1,
) -> dict[str, float]:
    if frames <= 0:
        raise ValueError(f"frames must be positive, got {frames}")
    if isinstance(orig, tuple) and frames != 1:
        raise ValueError("multi-frame metrics require an original YUV path, not a pre-read frame")

    orig_path = None if isinstance(orig, tuple) else Path(orig)
    scale = float(1 << max(0, rec_bitdepth - orig_bitdepth))
    maxval = float((1 << orig_bitdepth) - 1)
    names = ("Y", "U", "V")
    ws_mse = [0.0, 0.0, 0.0]
    cpp_mse = [0.0, 0.0, 0.0]
    s_mse = [0.0, 0.0, 0.0]

    for frame_idx in range(frames):
        orig_frame = orig if orig_path is None else read_yuv420_frame(
            orig_path, width, height, frame_idx=frame_idx, bitdepth=orig_bitdepth
        )
        rec = read_yuv420_frame(rec_path, width, height, frame_idx=frame_idx, bitdepth=rec_bitdepth)
        for idx in range(3):
            diff = rec[idx].astype(np.float64) / scale - orig_frame[idx].astype(np.float64)
            ws_mse[idx] += erp_ws_mse(diff, height, idx != 0)
            cpp_mse[idx] += cpp_mse_from_error(diff.astype(np.float64))
            if spsnr_table is not None:
                xi, yi, xic, yic = spsnr_table
                if idx == 0:
                    s_mse[idx] += spsnr_nn_mse(diff, xi, yi)
                else:
                    s_mse[idx] += spsnr_nn_mse(diff, xic, yic)

    ws_mse = [x / frames for x in ws_mse]
    cpp_mse = [x / frames for x in cpp_mse]
    s_mse = [x / frames for x in s_mse]
    out: dict[str, float] = {}
    for idx, name in enumerate(names):
        out[f"WS_{name}"] = psnr_from_mse(ws_mse[idx], maxval)
        out[f"CPP_{name}"] = psnr_from_mse(cpp_mse[idx], maxval)
        if spsnr_table is not None:
            out[f"S_{name}"] = psnr_from_mse(s_mse[idx], maxval)
    out["WS_YUV"] = yuv_psnr_from_mse(*ws_mse, maxval)
    out["CPP_YUV"] = yuv_psnr_from_mse(*cpp_mse, maxval)
    if spsnr_table is not None:
        out["S_YUV"] = yuv_psnr_from_mse(*s_mse, maxval)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orig", required=True, type=Path)
    ap.add_argument("--run-root", required=True, type=Path)
    ap.add_argument("--width", type=int, required=True)
    ap.add_argument("--height", type=int, required=True)
    ap.add_argument("--orig-bitdepth", type=int, default=8)
    ap.add_argument("--rec-bitdepth", type=int, default=10)
    ap.add_argument("--sphere-file", type=Path, help="360Lib SphFile for S-PSNR-NN, e.g. sphere_655362.txt")
    ap.add_argument("--qps", default="22,27,32,37")
    ap.add_argument("--frames", type=int, default=1)
    ap.add_argument("--out-prefix", required=True, type=Path)
    args = ap.parse_args()

    qps = [int(x) for x in args.qps.split(",") if x]
    spsnr_table = erp_spsnr_nn_indices(args.sphere_file, args.width, args.height) if args.sphere_file else None
    rows = []
    for qp in qps:
        case_dir = args.run_root / f"AerialCity_QP{qp}"
        bitrate_a, _, _, _, _ = parse_log(case_dir / "anchor.log")
        bitrate_p, _, _, _, _ = parse_log(case_dir / "proposed.log")
        anchor = compute_case_with_bitdepth(
            args.orig, case_dir / "anchor_rec.yuv", args.width, args.height, args.rec_bitdepth,
            args.orig_bitdepth, spsnr_table, args.frames
        )
        proposed = compute_case_with_bitdepth(
            args.orig, case_dir / "proposed_rec.yuv", args.width, args.height, args.rec_bitdepth,
            args.orig_bitdepth, spsnr_table, args.frames
        )
        row = {"QP": qp, "AnchorKbps": bitrate_a, "ProposedKbps": bitrate_p}
        for key, value in anchor.items():
            row[f"Anchor_{key}"] = value
        for key, value in proposed.items():
            row[f"Proposed_{key}"] = value
        rows.append(row)

    metrics = {}
    rates_a = [r["AnchorKbps"] for r in rows]
    rates_p = [r["ProposedKbps"] for r in rows]
    metric_names = ("WS", "S", "CPP") if spsnr_table is not None else ("WS", "CPP")
    for metric in metric_names:
        for comp in ("Y", "U", "V", "YUV"):
            key = f"{metric}_{comp}"
            metrics[f"{key}_BDBR_pct"] = bdrate(
                rates_a,
                [r[f"Anchor_{key}"] for r in rows],
                rates_p,
                [r[f"Proposed_{key}"] for r in rows],
            )

    csv_path = args.out_prefix.with_suffix(".csv")
    json_path = args.out_prefix.with_suffix(".json")
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(csv_path)
    print(json_path)
    for row in rows:
        print(
            f"QP{row['QP']}: WS-Y {row['Anchor_WS_Y']:.4f}->{row['Proposed_WS_Y']:.4f}, "
            + (f"S-Y {row['Anchor_S_Y']:.4f}->{row['Proposed_S_Y']:.4f}, " if spsnr_table is not None else "")
            + f"CPP-Y {row['Anchor_CPP_Y']:.4f}->{row['Proposed_CPP_Y']:.4f}"
        )
    for key, value in metrics.items():
        print(f"{key}={value:.6f}")


if __name__ == "__main__":
    main()
