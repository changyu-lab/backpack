#!/usr/bin/env python3
"""Scan LardLfnstSkip=10 second-response parameters on one ERP sequence."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import subprocess
import time
from pathlib import Path

from lard_360_metrics import (
    bdrate,
    compute_case_with_bitdepth,
    erp_spsnr_nn_indices,
    parse_log,
)


def run(cmd: list[str], log_path: Path) -> float:
    start = time.perf_counter()
    with log_path.open("w", encoding="utf-16") as log:
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, text=True)
    elapsed = time.perf_counter() - start
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")
    return elapsed


def encode(
    encoder: Path,
    orig: Path,
    width: int,
    height: int,
    fps: int,
    qp: int,
    frames: int,
    threads: int,
    preset: str,
    additional: str,
    out_dir: Path,
    tag: str,
) -> tuple[Path, Path, Path, float]:
    out_dir.mkdir(parents=True, exist_ok=True)
    bitstream = out_dir / f"{tag}.vvc"
    rec = out_dir / f"{tag}_rec.yuv"
    log = out_dir / f"{tag}.log"
    for path in (bitstream, rec, log):
      if path.exists():
        path.unlink()
    cmd = [
        str(encoder),
        "--preset", preset,
        "-i", str(orig),
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "--InputChromaFormat", "420",
        "-q", str(qp),
        "--qpa", "0",
        "-f", str(frames),
        "-ip", "1",
        "--mtprofile", "0",
        "--threads", str(threads),
        "--additional", additional,
        "-b", str(bitstream),
        "-o", str(rec),
    ]
    elapsed = run(cmd, log)
    return bitstream, rec, log, elapsed


def summarize(rows: list[dict[str, float | int | str]], out_json: Path) -> dict[str, float]:
    rates_a = [float(r["AnchorKbps"]) for r in rows]
    rates_p = [float(r["ProposedKbps"]) for r in rows]
    out: dict[str, float] = {}
    for metric in ("WS", "S", "CPP"):
        for comp in ("Y", "U", "V", "YUV"):
            key = f"{metric}_{comp}"
            out[f"{key}_BDBR_pct"] = bdrate(
                rates_a,
                [float(r[f"Anchor_{key}"]) for r in rows],
                rates_p,
                [float(r[f"Proposed_{key}"]) for r in rows],
            )
    anchor_time = sum(float(r["AnchorSeconds"]) for r in rows)
    proposed_time = sum(float(r["ProposedSeconds"]) for r in rows)
    anchor_bytes = sum(int(r["AnchorBytes"]) for r in rows)
    proposed_bytes = sum(int(r["ProposedBytes"]) for r in rows)
    out["TS_pct"] = (anchor_time - proposed_time) / anchor_time * 100.0
    out["ByteDelta_pct"] = (proposed_bytes - anchor_bytes) / anchor_bytes * 100.0
    out["AnchorTime_sec"] = anchor_time
    out["ProposedTime_sec"] = proposed_time
    out_json.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out


def load_anchor_cache(path: Path) -> dict[int, dict[str, float | int]]:
    anchors: dict[int, dict[str, float | int]] = {}
    with path.open("r", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            qp = int(row["QP"])
            anchor: dict[str, float | int] = {
                "Kbps": float(row["AnchorKbps"]),
                "Seconds": float(row["AnchorSeconds"]),
                "Bytes": int(float(row["AnchorBytes"])),
            }
            for metric in ("WS", "S", "CPP"):
                for comp in ("Y", "U", "V", "YUV"):
                    key = f"{metric}_{comp}"
                    anchor[key] = float(row[f"Anchor_{key}"])
            anchors[qp] = anchor
    return anchors


def additional_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def cfg_float(value: float) -> str:
    text = f"{value:.9f}".rstrip("0").rstrip(".")
    return text if text and text != "-0" else "0"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--encoder", type=Path, default=Path(r"I:\vvenc-LFNST\bin\release-static\vvencFFapp.exe"))
    ap.add_argument("--orig", type=Path, required=True)
    ap.add_argument("--width", type=int, required=True)
    ap.add_argument("--height", type=int, required=True)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--orig-bitdepth", type=int, default=8)
    ap.add_argument("--rec-bitdepth", type=int, default=10)
    ap.add_argument("--sphere-file", type=Path, required=True)
    ap.add_argument("--out-root", type=Path, required=True)
    ap.add_argument("--qps", default="22,27,32,37")
    ap.add_argument("--frames", type=int, default=1)
    ap.add_argument("--threads", type=int, default=20)
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--skip-modes", default="10")
    ap.add_argument("--zetas", default="0.1,0.5,1.0")
    ap.add_argument("--deltas", default="0.25,1.0")
    ap.add_argument("--ridxs", default="1.0,2.0")
    ap.add_argument("--corr-alphas", default="0.0")
    ap.add_argument("--corr-decays", default="2.0")
    ap.add_argument("--corr-tables", default="0")
    ap.add_argument("--theory-tables", default="0")
    ap.add_argument("--safe-margins", default="0.0")
    ap.add_argument("--obs-gates", default="-1000000000.0")
    ap.add_argument("--stage1-relaxes", default="1.0")
    ap.add_argument("--stage1-relax-qpmaps", default="", help="optional QP-bucket overrides separated by '|', e.g. 22:2.5,27:2.5,32:1.5,37:1.25")
    ap.add_argument("--max-cu-qps", default="63")
    ap.add_argument("--min-areas", default="0")
    ap.add_argument("--min-widths", default="0")
    ap.add_argument("--min-heights", default="0")
    ap.add_argument("--max-aspects", default="4")
    ap.add_argument("--shape-masks", default="31")
    ap.add_argument("--eff-cols-gates", default="0")
    ap.add_argument("--eff-cols-mins", default="2")
    ap.add_argument("--eff-cols-only", default="0")
    ap.add_argument("--eff-cols-min-qpmaps", default="", help="optional QP-bucket effective-column thresholds separated by '|', e.g. 22:6,27:6,32:3,37:0")
    ap.add_argument("--min-dct2-costs", default="-1")
    ap.add_argument("--lard11-max-cu-qps", default="34")
    ap.add_argument("--lard11-min-areas", default="64")
    ap.add_argument("--lard11-min-widths", default="0")
    ap.add_argument("--lard11-min-heights", default="0")
    ap.add_argument("--lard11-min-dct2-costs", default="-1")
    ap.add_argument("--paper-grad-th1s", default="100")
    ap.add_argument("--paper-th2-scales", default="12.83")
    ap.add_argument("--paper-th2-offset1s", default="17.375")
    ap.add_argument("--paper-th2-offset2s", default="57.375")
    ap.add_argument("--lard13-fusions", default="1")
    ap.add_argument("--measure-only", default="0")
    ap.add_argument("--obs-only", default="0")
    ap.add_argument("--anchor-cache-csv", type=Path, default=None)
    ap.add_argument("--write-stats", action="store_true")
    ap.add_argument("--write-counts", action="store_true")
    args = ap.parse_args()

    qps = [int(x) for x in args.qps.split(",") if x]
    skip_modes = [int(x) for x in args.skip_modes.split(",") if x]
    zetas = [float(x) for x in args.zetas.split(",") if x]
    deltas = [float(x) for x in args.deltas.split(",") if x]
    ridxs = [float(x) for x in args.ridxs.split(",") if x]
    corr_alphas = [float(x) for x in args.corr_alphas.split(",") if x]
    corr_decays = [float(x) for x in args.corr_decays.split(",") if x]
    corr_tables = [int(x) for x in args.corr_tables.split(",") if x]
    theory_tables = [int(x) for x in args.theory_tables.split(",") if x]
    safe_margins = [float(x) for x in args.safe_margins.split(",") if x]
    obs_gates = [float(x) for x in args.obs_gates.split(",") if x]
    stage1_relaxes = [float(x) for x in args.stage1_relaxes.split(",") if x]
    stage1_relax_qpmaps = [x.strip() for x in args.stage1_relax_qpmaps.split("|") if x.strip()]
    if not stage1_relax_qpmaps:
        stage1_relax_qpmaps = [""]
    max_cu_qps = [int(x) for x in args.max_cu_qps.split(",") if x]
    min_areas = [int(x) for x in args.min_areas.split(",") if x]
    min_widths = [int(x) for x in args.min_widths.split(",") if x]
    min_heights = [int(x) for x in args.min_heights.split(",") if x]
    max_aspects = [float(x) for x in args.max_aspects.split(",") if x]
    shape_masks = [int(x, 0) for x in args.shape_masks.split(",") if x]
    eff_cols_gates = [int(x) for x in args.eff_cols_gates.split(",") if x]
    eff_cols_mins = [int(x) for x in args.eff_cols_mins.split(",") if x]
    eff_cols_only_values = [int(x) for x in args.eff_cols_only.split(",") if x]
    eff_cols_min_qpmaps = [x.strip() for x in args.eff_cols_min_qpmaps.split("|") if x.strip()]
    if not eff_cols_min_qpmaps:
        eff_cols_min_qpmaps = [""]
    min_dct2_costs = [float(x) for x in args.min_dct2_costs.split(",") if x]
    lard11_max_cu_qps = [int(x) for x in args.lard11_max_cu_qps.split(",") if x]
    lard11_min_areas = [int(x) for x in args.lard11_min_areas.split(",") if x]
    lard11_min_widths = [int(x) for x in args.lard11_min_widths.split(",") if x]
    lard11_min_heights = [int(x) for x in args.lard11_min_heights.split(",") if x]
    lard11_min_dct2_costs = [float(x) for x in args.lard11_min_dct2_costs.split(",") if x]
    paper_grad_th1s = [float(x) for x in args.paper_grad_th1s.split(",") if x]
    paper_th2_scales = [float(x) for x in args.paper_th2_scales.split(",") if x]
    paper_th2_offset1s = [float(x) for x in args.paper_th2_offset1s.split(",") if x]
    paper_th2_offset2s = [float(x) for x in args.paper_th2_offset2s.split(",") if x]
    lard13_fusions = [int(x) for x in args.lard13_fusions.split(",") if x]
    measure_only_values = [int(x) for x in args.measure_only.split(",") if x]
    obs_only_values = [int(x) for x in args.obs_only.split(",") if x]
    args.out_root.mkdir(parents=True, exist_ok=True)

    spsnr_table = erp_spsnr_nn_indices(args.sphere_file, args.width, args.height)

    if args.anchor_cache_csv:
        anchors = load_anchor_cache(args.anchor_cache_csv)
        missing_qps = [qp for qp in qps if qp not in anchors]
        if missing_qps:
            raise RuntimeError(f"anchor cache is missing QPs: {missing_qps}")
    else:
        anchors: dict[int, dict[str, float | int]] = {}
        for qp in qps:
            case_dir = args.out_root / "anchor" / f"QP{qp}"
            bitstream, rec, log, elapsed = encode(
                args.encoder, args.orig, args.width, args.height, args.fps, qp, args.frames,
                args.threads, args.preset, "LFNST=1 LardLfnstSkip=0", case_dir, "anchor"
            )
            metrics = compute_case_with_bitdepth(
                args.orig, rec, args.width, args.height, args.rec_bitdepth, args.orig_bitdepth, spsnr_table, args.frames
            )
            bitrate, _, _, _, _ = parse_log(log)
            metrics["Kbps"] = bitrate
            anchors[qp] = {
                **metrics,
                "Seconds": elapsed,
                "Bytes": bitstream.stat().st_size,
            }

    summary_rows: list[dict[str, float | str]] = []
    for zeta in zetas:
        for delta in deltas:
            for ridx in ridxs:
                for corr_alpha in corr_alphas:
                    for corr_decay in corr_decays:
                        for corr_table in corr_tables:
                            for safe_margin in safe_margins:
                                for obs_gate in obs_gates:
                                    for stage1_relax in stage1_relaxes:
                                        for qpmap in stage1_relax_qpmaps:
                                            qp_overrides: dict[int, float] = {}
                                            for item in qpmap.split(","):
                                                if not item:
                                                    continue
                                                key, value = item.split(":", 1)
                                                qp_overrides[int(key)] = float(value)
                                            qpmap_tag = "base" if not qpmap else qpmap.replace(":", "v").replace(",", "_")
                                            for eff_cols_qpmap in eff_cols_min_qpmaps:
                                                eff_cols_overrides: dict[int, int] = {}
                                                for item in eff_cols_qpmap.split(","):
                                                    if not item:
                                                        continue
                                                    key, value = item.split(":", 1)
                                                    eff_cols_overrides[int(key)] = int(value)
                                                eff_qpmap_tag = "base" if not eff_cols_qpmap else eff_cols_qpmap.replace(":", "v").replace(",", "_")
                                                for skip_mode, theory_table, max_cu_qp, min_area, min_width, min_height, max_aspect, shape_mask, eff_cols_gate, eff_cols_min, eff_cols_only, min_dct2_cost, lard11_max_cu_qp, lard11_min_area, lard11_min_width, lard11_min_height, lard11_min_dct2_cost, paper_grad_th1, paper_th2_scale, paper_th2_offset1, paper_th2_offset2, lard13_fusion, measure_only, obs_only in itertools.product(
                                                    skip_modes,
                                                    theory_tables,
                                                    max_cu_qps,
                                                    min_areas,
                                                    min_widths,
                                                    min_heights,
                                                    max_aspects,
                                                    shape_masks,
                                                    eff_cols_gates,
                                                    eff_cols_mins,
                                                    eff_cols_only_values,
                                                    min_dct2_costs,
                                                    lard11_max_cu_qps,
                                                    lard11_min_areas,
                                                    lard11_min_widths,
                                                    lard11_min_heights,
                                                    lard11_min_dct2_costs,
                                                    paper_grad_th1s,
                                                    paper_th2_scales,
                                                    paper_th2_offset1s,
                                                    paper_th2_offset2s,
                                                    lard13_fusions,
                                                    measure_only_values,
                                                    obs_only_values,
                                                ):
                                                    md_tag = cfg_float(min_dct2_cost).replace(".", "p").replace("-", "m")
                                                    l11md_tag = cfg_float(lard11_min_dct2_cost).replace(".", "p").replace("-", "m")
                                                    mx_tag = cfg_float(max_aspect).replace(".", "p").replace("-", "m")
                                                    p1_tag = cfg_float(paper_grad_th1).replace(".", "p").replace("-", "m")
                                                    ps_tag = cfg_float(paper_th2_scale).replace(".", "p").replace("-", "m")
                                                    po1_tag = cfg_float(paper_th2_offset1).replace(".", "p").replace("-", "m")
                                                    po2_tag = cfg_float(paper_th2_offset2).replace(".", "p").replace("-", "m")
                                                    tag = f"sk{skip_mode}_z{cfg_float(zeta)}_d{cfg_float(delta)}_r{cfg_float(ridx)}_c{cfg_float(corr_alpha)}_cd{cfg_float(corr_decay)}_ct{corr_table}_tt{theory_table}_sm{cfg_float(safe_margin)}_og{cfg_float(obs_gate)}_sr{cfg_float(stage1_relax)}_qpm{qpmap_tag}_mq{max_cu_qp}_ma{min_area}_mw{min_width}_mh{min_height}_mx{mx_tag}_sh{shape_mask}_ec{eff_cols_gate}_em{eff_cols_min}_eo{eff_cols_only}_eqpm{eff_qpmap_tag}_md{md_tag}_l11mq{lard11_max_cu_qp}_l11ma{lard11_min_area}_l11mw{lard11_min_width}_l11mh{lard11_min_height}_l11md{l11md_tag}_pth1{p1_tag}_pts{ps_tag}_po1{po1_tag}_po2{po2_tag}_f13{lard13_fusion}_mo{measure_only}_oo{obs_only}".replace(".", "p").replace("-", "m")
                                                    rows: list[dict[str, float | int | str]] = []
                                                    run_dir = args.out_root / tag
                                                    for qp in qps:
                                                        additional = (
                                                            f"LFNST=1 LardLfnstSkip={skip_mode} LardLfnst2ndZeta={cfg_float(zeta)} "
                                                            f"LardLfnst2ndDelta={cfg_float(delta)} LardLfnst2ndRidx={cfg_float(ridx)} "
                                                            f"LardLfnst2ndCorrAlpha={cfg_float(corr_alpha)} LardLfnst2ndCorrDecay={cfg_float(corr_decay)} "
                                                            f"LardLfnst2ndCorrTable={corr_table} "
                                                            f"LardLfnstTheoryTable={theory_table} "
                                                            f"LardLfnst2ndSafeMargin={cfg_float(safe_margin)} "
                                                            f"LardLfnst2ndObsGate={cfg_float(obs_gate)} "
                                                            f"LardLfnst2ndStage1Relax={cfg_float(stage1_relax)} "
                                                            f"LardLfnst2ndMaxCuQp={max_cu_qp} "
                                                            f"LardLfnst2ndMinArea={min_area} "
                                                            f"LardLfnst2ndMinWidth={min_width} "
                                                            f"LardLfnst2ndMinHeight={min_height} "
                                                            f"LardLfnst2ndMaxAspect={cfg_float(max_aspect)} "
                                                            f"LardLfnst2ndShapeMask={shape_mask} "
                                                            f"LardLfnst2ndEffColsGate={eff_cols_gate} "
                                                            f"LardLfnst2ndEffColsMin={eff_cols_min} "
                                                            f"LardLfnst2ndEffColsOnly={eff_cols_only} "
                                                            f"LardLfnst2ndMinDct2Cost={cfg_float(min_dct2_cost)} "
                                                            f"LardLfnst11MaxCuQp={lard11_max_cu_qp} "
                                                            f"LardLfnst11MinArea={lard11_min_area} "
                                                            f"LardLfnst11MinWidth={lard11_min_width} "
                                                            f"LardLfnst11MinHeight={lard11_min_height} "
                                                            f"LardLfnst11MinDct2Cost={cfg_float(lard11_min_dct2_cost)} "
                                                            f"LardLfnstPaperGradTh1={cfg_float(paper_grad_th1)} "
                                                            f"LardLfnstPaperTh2Scale={cfg_float(paper_th2_scale)} "
                                                            f"LardLfnstPaperTh2Offset1={cfg_float(paper_th2_offset1)} "
                                                            f"LardLfnstPaperTh2Offset2={cfg_float(paper_th2_offset2)} "
                                                            f"LardLfnst13Fusion={lard13_fusion} "
                                                            f"LardLfnst2ndMeasureOnly={measure_only} "
                                                            f"LardLfnst2ndObsOnly={obs_only}"
                                                        )
                                                        for bucket_qp, relax_value in sorted(qp_overrides.items()):
                                                            additional += f" LardLfnst2ndStage1RelaxQp{bucket_qp}={cfg_float(relax_value)}"
                                                        for bucket_qp, min_value in sorted(eff_cols_overrides.items()):
                                                            additional += f" LardLfnst2ndEffColsMinQp{bucket_qp}={min_value}"
                                                        if args.write_stats:
                                                            additional += f" LardLfnst2ndStatFile={additional_path(run_dir / ('QP' + str(qp)) / 'lfnst2nd_stats.csv')}"
                                                        if args.write_counts:
                                                            additional += f" LardLfnst2ndCountFile={additional_path(run_dir / ('QP' + str(qp)) / 'lfnst2nd_counts.csv')}"
                                                        bitstream, rec, log, elapsed = encode(
                                                            args.encoder, args.orig, args.width, args.height, args.fps, qp, args.frames,
                                                            args.threads, args.preset, additional, run_dir / f"QP{qp}", "proposed"
                                                        )
                                                        proposed = compute_case_with_bitdepth(
                                                            args.orig, rec, args.width, args.height, args.rec_bitdepth,
                                                            args.orig_bitdepth, spsnr_table, args.frames
                                                        )
                                                        bitrate, _, _, _, _ = parse_log(log)
                                                        proposed["Kbps"] = bitrate

                                                        row: dict[str, float | int | str] = {"QP": qp}
                                                        row["AnchorKbps"] = float(anchors[qp]["Kbps"])
                                                        row["ProposedKbps"] = proposed["Kbps"]
                                                        for key, value in anchors[qp].items():
                                                            if key in ("Seconds", "Bytes"):
                                                                continue
                                                            row[f"Anchor_{key}"] = value
                                                        for key, value in proposed.items():
                                                            row[f"Proposed_{key}"] = value
                                                        row["AnchorSeconds"] = float(anchors[qp]["Seconds"])
                                                        row["ProposedSeconds"] = elapsed
                                                        row["AnchorBytes"] = int(anchors[qp]["Bytes"])
                                                        row["ProposedBytes"] = bitstream.stat().st_size
                                                        rows.append(row)
                                                        rec.unlink(missing_ok=True)

                                                    with (run_dir / "metric_curve.csv").open("w", newline="", encoding="utf-8") as fh:
                                                        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                                                        writer.writeheader()
                                                        writer.writerows(rows)
                                                    metrics_out = summarize(rows, run_dir / "metrics.json")
                                                    summary_rows.append({
                                                        "tag": tag,
                                                        "skip_mode": skip_mode,
                                                        "zeta": zeta,
                                                        "delta": delta,
                                                        "ridx": ridx,
                                                        "corr_alpha": corr_alpha,
                                                        "corr_decay": corr_decay,
                                                        "corr_table": corr_table,
                                                        "theory_table": theory_table,
                                                        "safe_margin": safe_margin,
                                                        "obs_gate": obs_gate,
                                                        "stage1_relax": stage1_relax,
                                                        "stage1_relax_qpmap": qpmap,
                                                        "max_cu_qp": max_cu_qp,
                                                        "min_area": min_area,
                                                        "min_width": min_width,
                                                        "min_height": min_height,
                                                        "max_aspect": max_aspect,
                                                        "shape_mask": shape_mask,
                                                        "eff_cols_gate": eff_cols_gate,
                                                        "eff_cols_min": eff_cols_min,
                                                        "eff_cols_only": eff_cols_only,
                                                        "eff_cols_min_qpmap": eff_cols_qpmap,
                                                        "min_dct2_cost": min_dct2_cost,
                                                        "lard11_max_cu_qp": lard11_max_cu_qp,
                                                        "lard11_min_area": lard11_min_area,
                                                        "lard11_min_width": lard11_min_width,
                                                        "lard11_min_height": lard11_min_height,
                                                        "lard11_min_dct2_cost": lard11_min_dct2_cost,
                                                        "paper_grad_th1": paper_grad_th1,
                                                        "paper_th2_scale": paper_th2_scale,
                                                        "paper_th2_offset1": paper_th2_offset1,
                                                        "paper_th2_offset2": paper_th2_offset2,
                                                        "lard13_fusion": lard13_fusion,
                                                        "measure_only": measure_only,
                                                        "obs_only": obs_only,
                                                        "WS_YUV_BDBR_pct": metrics_out["WS_YUV_BDBR_pct"],
                                                        "S_YUV_BDBR_pct": metrics_out["S_YUV_BDBR_pct"],
                                                        "CPP_YUV_BDBR_pct": metrics_out["CPP_YUV_BDBR_pct"],
                                                        "TS_pct": metrics_out["TS_pct"],
                                                        "ByteDelta_pct": metrics_out["ByteDelta_pct"],
                                                    })
                                                    print(json.dumps(summary_rows[-1], ensure_ascii=False))

    with (args.out_root / "scan_summary.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)


if __name__ == "__main__":
    main()
