#!/usr/bin/env python3
"""Generate unit-residual-variance covariance templates for LFNST Skip15."""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from compute_lfnst_theory_stats import dct2_orthonormal_matrix, parse_rom_lfnst


LAT_BINS = [0, 15, 30, 45, 60, 75, 85]
SIZES = [
    (4, 4), (4, 8), (8, 4),
    (8, 8), (8, 16), (16, 8),
    (16, 16), (16, 32), (32, 16),
    (32, 32),
]
RHO_H = 0.6
RHO_V = 0.6
EPS = 1e-12


def corr_matrix_h(width: int, theta_deg: float, rho_h: float = RHO_H) -> np.ndarray:
    idx = np.arange(width)
    distance = np.abs(idx[:, None] - idx[None, :])
    return rho_h ** (distance * np.cos(np.deg2rad(abs(theta_deg))))


def corr_matrix_v(height: int, rho_v: float = RHO_V) -> np.ndarray:
    idx = np.arange(height)
    return rho_v ** np.abs(idx[:, None] - idx[None, :])


def lfnst_positions(width: int, height: int, sb_size: int, transpose: bool) -> list[tuple[int, int]]:
    if sb_size == 4:
        if width < 4 or height < 4:
            raise ValueError(f"invalid 4x4 LFNST ROI for {width}x{height}")
        if transpose:
            return [(x, y) for x in range(4) for y in range(4)]
        return [(x, y) for y in range(4) for x in range(4)]
    if sb_size != 8 or width < 8 or height < 8:
        raise ValueError(f"invalid 8x8 LFNST ROI for {width}x{height}")
    if transpose:
        return (
            [(x, y) for x in range(4) for y in range(8)]
            + [(x, y) for x in range(4, 8) for y in range(4)]
        )
    return [(x, y) for y in range(8) for x in range(8 if y < 4 else 4)]


def zero_out_size(width: int, height: int) -> int:
    return 8 if (width, height) in {(4, 4), (8, 8)} else 16


def covariance_roi(width: int, height: int, theta_deg: float, transpose: bool) -> np.ndarray:
    ah = dct2_orthonormal_matrix(width)
    av = dct2_orthonormal_matrix(height)
    ch = ah @ corr_matrix_h(width, theta_deg) @ ah.T
    cv = av @ corr_matrix_v(height) @ av.T
    sb_size = 8 if width >= 8 and height >= 8 else 4
    positions = lfnst_positions(width, height, sb_size, transpose)
    sigma_x = np.empty((len(positions), len(positions)), dtype=np.float64)
    for i, (xi, yi) in enumerate(positions):
        for j, (xj, yj) in enumerate(positions):
            sigma_x[i, j] = cv[yi, yj] * ch[xi, xj]
    return (sigma_x + sigma_x.T) * 0.5


def generate_entries(rom_lfnst: Path) -> list[dict[str, object]]:
    lfnst8, lfnst4, _, _ = parse_rom_lfnst(rom_lfnst)
    entries: list[dict[str, object]] = []
    for lat_index, theta in enumerate(LAT_BINS):
        for width, height in SIZES:
            sb_size = 8 if width >= 8 and height >= 8 else 4
            k_in = 48 if sb_size == 8 else 16
            out_n = zero_out_size(width, height)
            for transpose in (0, 1):
                sigma_x = covariance_roi(width, height, theta, bool(transpose))
                eig = np.linalg.eigvalsh(sigma_x)
                if float(eig.min()) < -1e-8:
                    raise ValueError(f"Sigma_x is not PSD: theta={theta}, size={width}x{height}, tr={transpose}")
                var_x = np.maximum(np.diag(sigma_x), 0.0)
                for set_idx in range(4):
                    source = lfnst8 if sb_size == 8 else lfnst4
                    var_y = np.zeros((2, 16), dtype=np.float64)
                    exp_retained = np.zeros(2, dtype=np.float64)
                    exp_zero = np.zeros(2, dtype=np.float64)
                    for cand in range(2):
                        s_full = source[set_idx, cand, :16, :k_in].astype(np.float64)
                        sigma_y_full = s_full @ sigma_x @ s_full.T
                        diag_full = np.maximum(np.diag(sigma_y_full), 0.0)
                        var_y[cand, :out_n] = diag_full[:out_n]
                        exp_retained[cand] = float(np.sum(diag_full[:out_n]))
                        exp_zero[cand] = float(np.sum(diag_full[out_n:16]))
                    entries.append(
                        {
                            "latBin": lat_index,
                            "latDeg": theta,
                            "W": width,
                            "H": height,
                            "setIdx": set_idx,
                            "transpose": transpose,
                            "sbSize": sb_size,
                            "kIn": k_in,
                            "outN": out_n,
                            "varX": var_x,
                            "varY": var_y,
                            "expRetainedEnergy": exp_retained,
                            "expZeroEnergy": exp_zero,
                            "minEigX": float(eig.min()),
                        }
                    )
    return entries


def format_float_array(values: np.ndarray, count: int) -> str:
    padded = np.zeros(count, dtype=np.float64)
    padded[: min(len(values), count)] = values[:count]
    literals = []
    for value in padded:
        literal = f"{float(value):.9g}"
        if "." not in literal and "e" not in literal.lower():
            literal += ".0"
        literals.append(literal + "f")
    return ", ".join(literals)


def write_cpp(entries: list[dict[str, object]], out_dir: Path) -> None:
    header = out_dir / "LardLfnstCovTable.h"
    source = out_dir / "LardLfnstCovTable.cpp"
    header.write_text(
        """#pragma once
#include <cstdint>

namespace vvenc {

struct LardLfnstCovEntry
{
  uint8_t latBin;
  uint8_t width;
  uint8_t height;
  uint8_t setIdx;
  uint8_t transpose;
  uint8_t sbSize;
  uint8_t kIn;
  uint8_t outN;
  float varX[48];
  float varY[2][16];
  float expRetainedEnergy[2];
  float expZeroEnergy[2];
};

const LardLfnstCovEntry* getLardLfnstCovEntry( int latBin, int width, int height, int setIdx, bool transpose );
int getLardLfnstCovTableSize();

} // namespace vvenc
""",
        encoding="utf-8",
    )
    lines = [
        '#include "LardLfnstCovTable.h"',
        "",
        "namespace vvenc {",
        "",
        "static const LardLfnstCovEntry g_lardLfnstCovTable[] =",
        "{",
    ]
    for e in entries:
        var_x = np.asarray(e["varX"])
        var_y = np.asarray(e["varY"])
        exp_retained = np.asarray(e["expRetainedEnergy"])
        exp_zero = np.asarray(e["expZeroEnergy"])
        lines.extend(
            [
                "  {",
                f"    {e['latBin']}, {e['W']}, {e['H']}, {e['setIdx']}, {e['transpose']}, {e['sbSize']}, {e['kIn']}, {e['outN']},",
                f"    {{ {format_float_array(var_x, 48)} }},",
                "    {",
                f"      {{ {format_float_array(var_y[0], 16)} }},",
                f"      {{ {format_float_array(var_y[1], 16)} }}",
                "    },",
                f"    {{ {format_float_array(exp_retained, 2)} }},",
                f"    {{ {format_float_array(exp_zero, 2)} }}",
                "  },",
            ]
        )
    lines.extend(
        [
            "};",
            "",
            "const LardLfnstCovEntry* getLardLfnstCovEntry( int latBin, int width, int height, int setIdx, bool transpose )",
            "{",
            "  for( const auto& entry : g_lardLfnstCovTable )",
            "  {",
            "    if( entry.latBin == latBin && entry.width == width && entry.height == height",
            "        && entry.setIdx == setIdx && entry.transpose == int( transpose ) )",
            "    {",
            "      return &entry;",
            "    }",
            "  }",
            "  return nullptr;",
            "}",
            "",
            "int getLardLfnstCovTableSize()",
            "{",
            "  return int( sizeof( g_lardLfnstCovTable ) / sizeof( g_lardLfnstCovTable[0] ) );",
            "}",
            "",
            "} // namespace vvenc",
            "",
        ]
    )
    source.write_text("\n".join(lines), encoding="utf-8")


def write_debug(entries: list[dict[str, object]], out_dir: Path) -> None:
    metadata = []
    var_x = np.zeros((len(entries), 48), dtype=np.float64)
    var_y = np.zeros((len(entries), 2, 16), dtype=np.float64)
    for index, entry in enumerate(entries):
        vx = np.asarray(entry["varX"])
        vy = np.asarray(entry["varY"])
        var_x[index, : len(vx)] = vx
        var_y[index] = vy
        metadata.append([entry[k] for k in ("latBin", "latDeg", "W", "H", "setIdx", "transpose", "sbSize", "kIn", "outN")])
    np.savez_compressed(out_dir / "lard_lfnst_cov_debug.npz", metadata=np.asarray(metadata), varX=var_x, varY=var_y)

    fields = [
        "latBin", "latDeg", "W", "H", "sbSize", "transpose", "setIdx", "kIn", "outN",
        "traceX", "traceY1", "traceY2", "entropyX", "entropyY1", "entropyY2",
        "expRetainedY1", "expRetainedY2", "expZeroY1", "expZeroY2",
        "minEigX", "minVarX", "minVarY",
    ]
    with (out_dir / "lard_lfnst_cov_summary.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for e in entries:
            vx = np.asarray(e["varX"])
            vy = np.asarray(e["varY"])
            exp_retained = np.asarray(e["expRetainedEnergy"])
            exp_zero = np.asarray(e["expZeroEnergy"])
            entropy = lambda v: float(-np.sum((v / (np.sum(v) + EPS)) * np.log2(v / (np.sum(v) + EPS) + EPS)))
            writer.writerow(
                {
                    **{k: e[k] for k in ("latBin", "latDeg", "W", "H", "sbSize", "transpose", "setIdx", "kIn", "outN")},
                    "traceX": float(vx.sum()),
                    "traceY1": float(vy[0].sum()),
                    "traceY2": float(vy[1].sum()),
                    "entropyX": entropy(vx),
                    "entropyY1": entropy(vy[0]),
                    "entropyY2": entropy(vy[1]),
                    "expRetainedY1": float(exp_retained[0]),
                    "expRetainedY2": float(exp_retained[1]),
                    "expZeroY1": float(exp_zero[0]),
                    "expZeroY2": float(exp_zero[1]),
                    "minEigX": e["minEigX"],
                    "minVarX": float(vx.min()),
                    "minVarY": float(vy.min()),
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom-lfnst", type=Path, default=Path("source/Lib/CommonLib/Rom.cpp"))
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    entries = generate_entries(args.rom_lfnst)
    write_cpp(entries, args.out_dir)
    write_debug(entries, args.out_dir)
    print(f"generated {len(entries)} entries in {args.out_dir}")


if __name__ == "__main__":
    main()
