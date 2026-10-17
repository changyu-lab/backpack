#!/usr/bin/env python3
"""
Compute projection-conditioned LFNST theoretical statistics.

This script has two modes:
1) input-only mode: computes Sigma_x, v0, Rx, C_off, rho_eig, H0 etc.
2) full mode: if --rom-lfnst path/to/Rom.cpp is provided, parses VVenC
   g_lfnstFwd8x8[4][2][16][48] and g_lfnstFwd4x4[4][2][16][16], computes
   v_l, H_l, energy compaction, and DeltaR LUT.

Assumptions for the theoretical model:
- unit residual variance: sigma_r^2 = 1. Online variance scales all variances.
- ERP horizontal stretching is modeled by Rh_phi[i,j] = rho_h ** (abs(i-j)*cos(abs(phi))).
- vertical correlation is Rv[i,j] = rho_v ** abs(i-j).
- --model dct_ortho uses an orthonormal DCT-II primary-transform analysis core.
- --model vvenc_int parses VVenC integer DCT-II cores and normalizes rows to unit norm.
- LFNST vectorization order follows VTM TrQuant::xFwdLfnst, including transposeFlag.
- LFNST matrices in Rom.cpp are int8 and are normalized by 128.0, consistent with forward >>7 scaling.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np

EPS = 1e-12


def dct2_orthonormal_matrix(n: int) -> np.ndarray:
    A = np.zeros((n, n), dtype=np.float64)
    for k in range(n):
        alpha = math.sqrt(1.0 / n) if k == 0 else math.sqrt(2.0 / n)
        for x in range(n):
            A[k, x] = alpha * math.cos(math.pi * (2 * x + 1) * k / (2 * n))
    return A


def lfnst_input_coords(W: int, H: int, s: int, transpose: int) -> List[Tuple[int, int]]:
    """Return input-vector coordinate order (u, v) matching VTM xFwdLfnst vectorization.

    For s=4: top-left 4x4, K=16.
    For s=8: L-shaped 8x8 ROI, K=48: top four 8-wide rows plus lower four 4-wide rows.
    transpose=1 applies the transposeFlag vectorization used in VTM.
    """
    if s == 4:
        if W < 4 or H < 4:
            raise ValueError(f"s=4 requires W,H>=4, got {W}x{H}")
        coords = [None] * 16
        if not transpose:
            k = 0
            for y in range(4):
                for x in range(4):
                    coords[k] = (x, y)
                    k += 1
        else:
            for y in range(4):
                for x in range(4):
                    coords[y + 4 * x] = (x, y)
        return coords
    elif s == 8:
        if W < 8 or H < 8:
            raise ValueError(f"s=8 requires W,H>=8, got {W}x{H}")
        coords = [None] * 48
        if not transpose:
            k = 0
            for y in range(8):
                stride = 8 if y < 4 else 4
                for x in range(stride):
                    coords[k] = (x, y)
                    k += 1
        else:
            # This follows the assignments in TrQuant::xFwdLfnst.
            for y in range(8):
                for x in range(4):
                    coords[y + 8 * x] = (x, y)
                if y < 4:
                    for x in range(4, 8):
                        coords[32 + y + 4 * (x - 4)] = (x, y)
        return coords
    else:
        raise ValueError("s must be 4 or 8")


def corr_matrix(n: int, rho: float, exponent_scale: float = 1.0) -> np.ndarray:
    idx = np.arange(n)
    dist = np.abs(idx[:, None] - idx[None, :])
    return rho ** (dist * exponent_scale)


def normalize_cov_to_corr(Sigma: np.ndarray) -> np.ndarray:
    d = np.sqrt(np.maximum(np.diag(Sigma), EPS))
    return Sigma / (d[:, None] * d[None, :] + EPS)


def energy_entropy(v: np.ndarray) -> float:
    v = np.maximum(np.asarray(v, dtype=np.float64), 0.0)
    p = v / (np.sum(v) + EPS)
    return float(-np.sum(p * np.log(p + EPS)))


def effective_rank_from_eigvals(vals: np.ndarray) -> float:
    vals = np.maximum(np.asarray(vals, dtype=np.float64), 0.0)
    p = vals / (np.sum(vals) + EPS)
    return float(np.exp(-np.sum(p * np.log(p + EPS))))


def summary_stats(Sigma_x: np.ndarray) -> Dict[str, float]:
    K = Sigma_x.shape[0]
    v0 = np.diag(Sigma_x).copy()
    Rx = normalize_cov_to_corr(Sigma_x)
    off = Rx[~np.eye(K, dtype=bool)]
    C_off = float(np.mean(np.abs(off))) if off.size else 0.0
    off_sigma = Sigma_x - np.diag(v0)
    E_off = float(np.sum(off_sigma * off_sigma) / (np.sum(Sigma_x * Sigma_x) + EPS))
    eigvals = np.linalg.eigvalsh((Sigma_x + Sigma_x.T) * 0.5)
    eigvals = np.maximum(eigvals, 0.0)
    rho_eig = float(np.max(eigvals) / (np.sum(eigvals) + EPS))
    r_eff = effective_rank_from_eigvals(eigvals)
    H0 = energy_entropy(v0)
    v_sorted = np.sort(v0)[::-1]
    total = float(np.sum(v0) + EPS)
    return {
        "C_off": C_off,
        "E_off": E_off,
        "rho_eig": rho_eig,
        "r_eff": r_eff,
        "H0": H0,
        "top4_v0": float(np.sum(v_sorted[:min(4, K)]) / total),
        "top8_v0": float(np.sum(v_sorted[:min(8, K)]) / total),
        "top16_v0": float(np.sum(v_sorted[:min(16, K)]) / total),
        "trace_x": float(np.trace(Sigma_x)),
    }


def zero_out_size(W: int, H: int) -> int:
    return 8 if (W == 4 and H == 4) or (W == 8 and H == 8) else 16


def vvenc_lat_bucket(phi_deg: float) -> int:
    a = abs(phi_deg)
    if a < 30.0:
        return 0
    if a < 50.0:
        return 1
    if a < 70.0:
        return 2
    return 3


def effective_support_count(coords: List[Tuple[int, int]], W: int, phi_deg: float) -> int:
    mh = max(1, int(math.floor(W * math.cos(math.radians(abs(phi_deg))))))
    return sum(1 for u, _ in coords if u < mh)


def parse_romtr_dct2(path: Path) -> Dict[int, np.ndarray]:
    """Parse VVenC integer DCT-II forward cores from RomTr.cpp.

    The returned matrices are row-normalized to unit norm. This preserves the
    VVenC integer basis directions while keeping unit-variance covariance
    propagation numerically comparable with the orthonormal model.
    """
    text = path.read_text(encoding="utf-8", errors="ignore")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*", "", text)

    macros = {}
    raw_lines = text.splitlines()
    for line_idx, line in enumerate(raw_lines):
        m = re.match(r"\s*#define\s+(DEFINE_DCT2_P(?P<n>\d+)_MATRIX)\((?P<args>[^)]*)\)\s*(?P<body>.*)", line)
        if not m:
            continue
        n = int(m.group("n"))
        args = [a.strip() for a in m.group("args").split(",") if a.strip()]
        body_parts = [m.group("body").rstrip().rstrip("\\")]
        j = line_idx + 1
        while j < len(raw_lines):
            part = raw_lines[j].rstrip()
            body_parts.append(part.rstrip("\\").rstrip())
            if not part.endswith("\\"):
                break
            j += 1
        macros[n] = (m.group(1), args, "\n".join(body_parts))

    out: Dict[int, np.ndarray] = {}
    for n in [4, 8, 16, 32, 64]:
        if n not in macros:
            raise ValueError(f"Could not find DEFINE_DCT2_P{n}_MATRIX in {path}")
        name, args, body = macros[n]
        inv = re.search(rf"{name}\(([^)]*)\)", text[text.find(f"g_trCoreDCT2P{n}"):])
        if not inv:
            raise ValueError(f"Could not find g_trCoreDCT2P{n} invocation in {path}")
        vals = [int(x) for x in re.findall(r"[-+]?\d+", inv.group(1))]
        if len(vals) != len(args):
            raise ValueError(f"g_trCoreDCT2P{n}: expected {len(args)} macro args, got {len(vals)}")
        repl = {a: str(v) for a, v in zip(args, vals)}
        expanded = body
        for a in sorted(repl, key=len, reverse=True):
            expanded = re.sub(rf"\b{re.escape(a)}\b", repl[a], expanded)
        nums = [int(x) for x in re.findall(r"[-+]?\d+", expanded)]
        if len(nums) != n * n:
            raise ValueError(f"g_trCoreDCT2P{n}: expected {n*n} matrix entries, got {len(nums)}")
        A = np.asarray(nums, dtype=np.float64).reshape(n, n)
        row_norm = np.linalg.norm(A, axis=1)
        out[n] = A / np.maximum(row_norm[:, None], EPS)
    return out


def compute_sigma_x(W: int, H: int, phi_deg: float, rho_h: float, rho_v: float, transpose: int,
                    model: str, vvenc_dct2: Dict[int, np.ndarray] | None = None) -> Tuple[int, List[Tuple[int, int]], np.ndarray, Dict[str, float]]:
    cos_phi = math.cos(math.radians(abs(phi_deg)))
    Rh = corr_matrix(W, rho_h, cos_phi)
    Rv = corr_matrix(H, rho_v, 1.0)
    if model == "vvenc_int":
        if vvenc_dct2 is None or W not in vvenc_dct2 or H not in vvenc_dct2:
            raise ValueError("vvenc_int model requires parsed VVenC DCT-II cores for all sizes")
        Ah = vvenc_dct2[W]
        Av = vvenc_dct2[H]
    else:
        Ah = dct2_orthonormal_matrix(W)
        Av = dct2_orthonormal_matrix(H)
    Hh = Ah @ Rh @ Ah.T
    Hv = Av @ Rv @ Av.T
    s = 4 if min(W, H) == 4 else 8
    coords = lfnst_input_coords(W, H, s, transpose)
    K = len(coords)
    Sigma_x = np.zeros((K, K), dtype=np.float64)
    for p, (up, vp) in enumerate(coords):
        for q, (uq, vq) in enumerate(coords):
            Sigma_x[p, q] = Hh[up, uq] * Hv[vp, vq]
    return s, coords, Sigma_x, summary_stats(Sigma_x)


def parse_rom_lfnst(path: Path) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Parse forward/inverse LFNST arrays from Rom.cpp.

    Returns:
      lfnst8: shape (4,2,16,48), scaled by 1/128.0
      lfnst4: shape (4,2,16,16), scaled by 1/128.0
      inv8: shape (4,2,48,16), scaled by 1/128.0
      inv4: shape (4,2,16,16), scaled by 1/128.0
    """
    text = path.read_text(encoding="utf-8", errors="ignore")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*", "", text)

    def extract_array(name: str, shape: Tuple[int, ...]) -> np.ndarray:
        m = re.search(rf"const\s+int8_t\s+{name}\s*\[[^\]]+\]\s*\[[^\]]+\]\s*\[[^\]]+\]\s*\[[^\]]+\]\s*=\s*\{{", text)
        if not m:
            raise ValueError(f"Could not find {name} in {path}")
        start = m.end() - 1
        depth = 0
        end = None
        for i in range(start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end is None:
            raise ValueError(f"Could not parse brace block for {name}")
        block = text[start:end]
        nums = [int(x) for x in re.findall(r"[-+]?\d+", block)]
        expected = int(np.prod(shape))
        if len(nums) != expected:
            raise ValueError(f"{name}: expected {expected} integers, got {len(nums)}")
        return (np.array(nums, dtype=np.float64).reshape(shape) / 128.0)

    lfnst8 = extract_array("g_lfnstFwd8x8", (4, 2, 16, 48))
    lfnst4 = extract_array("g_lfnstFwd4x4", (4, 2, 16, 16))
    inv8 = extract_array("g_lfnstInv8x8", (4, 2, 48, 16))
    inv4 = extract_array("g_lfnstInv4x4", (4, 2, 16, 16))
    return lfnst8, lfnst4, inv8, inv4


def candidate_stats(S: np.ndarray, Inv: np.ndarray, Sigma_x: np.ndarray, zero_out: int) -> Dict[str, object]:
    S_eff = S[:zero_out, :]
    Sigma_y = S_eff @ Sigma_x @ S_eff.T
    vl = np.diag(Sigma_y).copy()
    H_l = energy_entropy(vl)
    v_sorted = np.sort(vl)[::-1]
    total = float(np.sum(vl) + EPS)
    tr_size = Sigma_x.shape[0]
    Inv_eff = Inv[:, :zero_out]
    err = np.eye(tr_size, dtype=np.float64) - Inv_eff @ S_eff
    d_sub_unit = float(np.trace(err @ Sigma_x @ err.T))
    trace_vvt = float(np.sum(Inv_eff * Inv_eff))
    return {
        "vl": vl,
        "H_l": float(H_l),
        "top4_vl": float(np.sum(v_sorted[:min(4, len(v_sorted))]) / total),
        "top8_vl": float(np.sum(v_sorted[:min(8, len(v_sorted))]) / total),
        "top16_vl": float(np.sum(v_sorted[:min(16, len(v_sorted))]) / total),
        "trace_y": float(np.trace(Sigma_y)),
        "trace_vvt": trace_vvt,
        "d_sub_unit": d_sub_unit,
    }


def hbar_from_a_v(a: float, v: np.ndarray, kappa: float) -> float:
    return float(np.sum(0.5 * np.log2(1.0 + kappa * a * np.maximum(v, 0.0))))


def write_inc(path: Path, rows: List[Dict[str, object]], model: str, rho_h: float, rho_v: float,
              a_exps: List[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    inc_rows = [r for r in rows if "DeltaR" in r and abs(float(r["ba_log2"]) - round(float(r["ba_log2"]))) < 1e-9]
    inc_rows.sort(key=lambda r: (int(r["latBucket"]), int(r["W"]), int(r["H"]), int(r["transpose"]),
                                 int(r["zeroOutSize"]), int(r["t"]), int(r["l"]), int(round(float(r["ba_log2"])))))
    unique_rows = []
    seen = set()
    for r in inc_rows:
        key = (int(r["latBucket"]), int(r["W"]), int(r["H"]), int(r["transpose"]),
               int(r["zeroOutSize"]), int(r["t"]), int(r["l"]), int(round(float(r["ba_log2"]))))
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(r)
    dims = (4, 5, 5, 2, 4, 2, len(a_exps))
    row_by_key = {}
    for r in unique_rows:
        key = (int(r["latBucket"]), int(r["wIdx"]), int(r["hIdx"]), int(r["transpose"]),
               int(r["t"]), int(r["l"]) - 1, int(round(float(r["ba_log2"]))) - int(min(a_exps)))
        row_by_key[key] = r

    with path.open("w", encoding="utf-8", newline="\n") as f:
      f.write("// Auto-generated by tools/compute_lfnst_theory_stats.py. Do not edit manually.\n")
      f.write(f"// model={model}, rho_h={rho_h}, rho_v={rho_v}, unit residual variance, online score uses lambda*DeltaR.\n")
      f.write(f"// aBin is round(log2(sigma_r^2/qStep^2)); generated range [{int(min(a_exps))}, {int(max(a_exps))}].\n")
      f.write(f"// Flat order: latBucket, wIdx, hIdx, transposeFlag, lfnstSet, cand, aBinIndex. Entries={np.prod(dims)}.\n")
      for lat in range(dims[0]):
          for wi in range(dims[1]):
              for hi in range(dims[2]):
                  for tr in range(dims[3]):
                      for t in range(dims[4]):
                          for cand in range(dims[5]):
                              for ai in range(dims[6]):
                                  r = row_by_key.get((lat, wi, hi, tr, t, cand, ai))
                                  if r is None:
                                      raise ValueError(f"missing inc row for {(lat, wi, hi, tr, t, cand, ai)}")
                                  f.write("  { %.9g, %.9g, %.9g, %.9g },\n" % (
                                      float(r["R0"]), float(r["Rl"]), float(r["DeltaR"]), float(r["DeltaDNorm"])))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-prefix", default="lfnst_theory_rho06")
    ap.add_argument("--model", choices=["dct_ortho", "vvenc_int"], default="dct_ortho")
    ap.add_argument("--rho-h", type=float, default=0.6)
    ap.add_argument("--rho-v", type=float, default=0.6)
    ap.add_argument("--phis", default="0:89:1", help="e.g. 0:89:1 or comma list 0,15,30,45,60,75")
    ap.add_argument("--emit-inc-phis", default="15,40,60,80", help="phi list for C++ inc rows; defaults to VVenC lat-bucket centers")
    ap.add_argument("--sizes", default="4,8,16,32,64")
    ap.add_argument("--qp-list", default="22,27,32,37")
    ap.add_argument("--a-bins", default="-12:12:1", help="log2(sigma_r^2/Delta^2) representative exponents")
    ap.add_argument("--kappa", type=float, default=1.0)
    ap.add_argument("--r-idx", type=float, default=1.0, help="LFNST index bit proxy")
    ap.add_argument("--rom-lfnst", type=str, default="source/Lib/CommonLib/Rom.cpp", help="path to VVenC Rom.cpp")
    ap.add_argument("--rom-tr", type=str, default="source/Lib/CommonLib/RomTr.cpp", help="path to VVenC RomTr.cpp")
    ap.add_argument("--emit-inc", type=str, default=None, help="optional C++ .inc output path")
    ap.add_argument("--self-test", action="store_true", help="run shape and zeroOutSize self-tests then exit")
    args = ap.parse_args()

    def parse_range_or_list(s: str) -> List[float]:
        if ":" in s:
            a, b, step = [float(x) for x in s.split(":")]
            vals = []
            x = a
            while x <= b + 1e-9:
                vals.append(float(x))
                x += step
            return vals
        return [float(x) for x in s.split(",") if x.strip()]

    phis = parse_range_or_list(args.phis)
    inc_phis = parse_range_or_list(args.emit_inc_phis)
    sizes = [int(x) for x in args.sizes.split(",")]
    qps = [int(x) for x in args.qp_list.split(",")]
    a_exps = parse_range_or_list(args.a_bins)
    a_vals = [2.0 ** e for e in a_exps]

    lfnst8 = lfnst4 = inv8 = inv4 = None
    if args.rom_lfnst:
        lfnst8, lfnst4, inv8, inv4 = parse_rom_lfnst(Path(args.rom_lfnst))
        if lfnst8.shape != (4, 2, 16, 48) or lfnst4.shape != (4, 2, 16, 16) or inv8.shape != (4, 2, 48, 16) or inv4.shape != (4, 2, 16, 16):
            raise ValueError(f"unexpected LFNST ROM shapes: fwd8={lfnst8.shape}, fwd4={lfnst4.shape}, inv8={inv8.shape}, inv4={inv4.shape}")

    vvenc_dct2 = None
    if args.model == "vvenc_int":
        vvenc_dct2 = parse_romtr_dct2(Path(args.rom_tr))

    if args.self_test:
        assert lfnst8 is not None and lfnst4 is not None
        assert lfnst_input_coords(4, 4, 4, 0) == [(x, y) for y in range(4) for x in range(4)]
        assert lfnst_input_coords(4, 4, 4, 1)[:4] == [(0, y) for y in range(4)]
        assert len(lfnst_input_coords(8, 8, 8, 0)) == 48
        assert candidate_stats(lfnst4[0, 0], inv4[0, 0], np.eye(16), 8)["vl"].shape[0] == 8
        assert candidate_stats(lfnst4[0, 0], inv4[0, 0], np.eye(16), 16)["vl"].shape[0] == 16
        if args.model == "vvenc_int":
            assert vvenc_dct2 is not None and all(vvenc_dct2[n].shape == (n, n) for n in [4, 8, 16, 32, 64])
        print("self-test OK")
        return

    out_npz: Dict[str, np.ndarray] = {}
    summary_rows = []
    cand_rows = []
    rd_rows = []
    meta = {
        "rho_h": args.rho_h,
        "rho_v": args.rho_v,
        "model": args.model,
        "phis_deg_abs": phis,
        "sizes": sizes,
        "qp_list": qps,
        "a_bin_log2_values": a_exps,
        "kappa": args.kappa,
        "r_idx": args.r_idx,
        "has_rom_lfnst": bool(args.rom_lfnst),
        "notes": "Sigma_x and variances are unit-residual-variance templates. Online uses a=sigma_r^2/qStep^2 and lambda*DeltaR. LFNST matrices are scaled by 1/128 if Rom.cpp is provided.",
    }

    calc_phis = sorted(set(float(p) for p in (phis + (inc_phis if args.emit_inc else []))))
    size_to_idx = {v: i for i, v in enumerate(sizes)}
    for phi in calc_phis:
        for W in sizes:
            for H in sizes:
                if W < 4 or H < 4 or W > 64 or H > 64:
                    continue
                for transpose in [0, 1]:
                    s, coords, Sigma_x, st = compute_sigma_x(W, H, phi, args.rho_h, args.rho_v, transpose, args.model, vvenc_dct2)
                    zero_out = zero_out_size(W, H)
                    eff_support = effective_support_count(coords, W, phi)
                    lat_bucket = vvenc_lat_bucket(phi)
                    key = f"phi{int(round(phi)):02d}_W{W}_H{H}_s{s}_tr{transpose}"
                    out_npz[f"Sigma_x_{key}"] = Sigma_x.astype(np.float32)
                    out_npz[f"v0_{key}"] = np.diag(Sigma_x).astype(np.float32)
                    out_npz[f"coords_{key}"] = np.array(coords, dtype=np.int16)
                    row = {
                        "phi_abs_deg": phi, "latBucket": lat_bucket, "W": W, "H": H, "s": s, "K": len(coords),
                        "wIdx": size_to_idx[W], "hIdx": size_to_idx[H],
                        "transpose": transpose, "zeroOutSize": zero_out, "effectiveSupportCount": eff_support,
                        **st,
                    }
                    summary_rows.append(row)

                    if lfnst8 is not None:
                        lfnst = lfnst4 if s == 4 else lfnst8
                        inv_lfnst = inv4 if s == 4 else inv8
                        for t in range(4):
                            for l in range(2):
                                S = lfnst[t, l]
                                Inv = inv_lfnst[t, l]
                                cs = candidate_stats(S, Inv, Sigma_x, zero_out)
                                out_npz[f"vl_{key}_t{t}_l{l+1}"] = cs["vl"].astype(np.float32)
                                cand_row = {
                                    "phi_abs_deg": phi, "latBucket": lat_bucket, "W": W, "H": H, "s": s, "K": len(coords),
                                    "wIdx": size_to_idx[W], "hIdx": size_to_idx[H],
                                    "transpose": transpose, "zeroOutSize": zero_out, "effectiveSupportCount": eff_support,
                                    "t": t, "l": l + 1,
                                    "H_l": cs["H_l"], "G_ent": st["H0"] - cs["H_l"],
                                    "top4_vl": cs["top4_vl"], "top8_vl": cs["top8_vl"], "top16_vl": cs["top16_vl"], "trace_y": cs["trace_y"],
                                    "trace_vvt": cs["trace_vvt"], "d_sub_unit": cs["d_sub_unit"],
                                }
                                cand_rows.append(cand_row)

                                v0 = np.diag(Sigma_x)
                                vl = cs["vl"]
                                for qp in qps:
                                    for ba, a in zip(a_exps, a_vals):
                                        R0 = hbar_from_a_v(a, v0, args.kappa)
                                        Rl = hbar_from_a_v(a, vl, args.kappa) + args.r_idx
                                        dR = R0 - Rl
                                        dDNorm = ((len(coords) - float(cs["trace_vvt"])) / 12.0) - a * float(cs["d_sub_unit"])
                                        rd_rows.append({
                                            "phi_abs_deg": phi, "latBucket": lat_bucket, "W": W, "H": H, "s": s,
                                            "wIdx": size_to_idx[W], "hIdx": size_to_idx[H],
                                            "transpose": transpose, "zeroOutSize": zero_out,
                                            "t": t, "l": l + 1, "QP": qp, "ba_log2": ba,
                                            "R0": R0, "Rl": Rl, "DeltaR": dR, "DeltaDNorm": dDNorm,
                                        })

    prefix = Path(args.out_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    out_npz["metadata_json"] = np.array(json.dumps(meta, ensure_ascii=False), dtype=object)
    np.savez_compressed(prefix.with_suffix(".npz"), **out_npz)

    def write_csv(path: Path, rows: List[Dict[str, object]]):
        if not rows:
            return
        fields = list(rows[0].keys())
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in rows:
                w.writerow(r)

    write_csv(prefix.with_name(prefix.name + "_input_summary.csv"), summary_rows)
    write_csv(prefix.with_name(prefix.name + "_candidate_summary.csv"), cand_rows)
    write_csv(prefix.with_name(prefix.name + "_rd_proxy.csv"), rd_rows)
    prefix.with_name(prefix.name + "_metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.emit_inc:
        inc_phi_set = {float(p) for p in inc_phis}
        inc_rows = [r for r in rd_rows if float(r["phi_abs_deg"]) in inc_phi_set]
        write_inc(Path(args.emit_inc), inc_rows, args.model, args.rho_h, args.rho_v, a_exps)
        print(f"Saved {args.emit_inc}")

    print(f"Saved {prefix.with_suffix('.npz')}")
    print(f"Saved {prefix.with_name(prefix.name + '_input_summary.csv')}")
    if cand_rows:
        print(f"Saved {prefix.with_name(prefix.name + '_candidate_summary.csv')}")
        print(f"Saved {prefix.with_name(prefix.name + '_rd_proxy.csv')}")
    print(f"Saved {prefix.with_name(prefix.name + '_metadata.json')}")


if __name__ == "__main__":
    main()
