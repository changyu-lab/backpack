#!/usr/bin/env python3
"""Fit a direct final-score table for skip13 second-response LFNST pruning."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


def size_group(w: int, h: int) -> int:
    area = w * h
    mn = min(w, h)
    mx = max(w, h)
    if area <= 16:
        return 0
    if area <= 32:
        return 1
    if area <= 64:
        return 2
    if area <= 256:
        return 3
    if area <= 1024:
        return 4
    if mx >= 4 * mn:
        return 6
    return 5


def mode_group(mode: int) -> int:
    if mode == 0:
        return 0
    if mode == 1:
        return 1
    if mode <= 17:
        return 2
    if mode <= 34:
        return 3
    if mode <= 50:
        return 4
    return 5


def lat_bucket(abs_lat: float) -> int:
    if abs_lat < 30.0:
        return 0
    if abs_lat < 50.0:
        return 1
    if abs_lat < 70.0:
        return 2
    return 3


def corr_bucket(corr: float) -> int:
    if corr < 0.10:
        return 0
    if corr < 0.25:
        return 1
    if corr < 0.50:
        return 2
    if corr < 1.00:
        return 3
    return 4


def qstep(qp: int) -> float:
    q = min(63, max(0, qp))
    return 2.0 ** ((q - 4.0) / 6.0)


def energy_bucket(energy_norm: float) -> int:
    for idx, th in enumerate((0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0,
                              64.0, 128.0, 256.0, 512.0, 1024.0, 2048.0, 4096.0)):
        if energy_norm <= th:
            return idx
    return 15


def obs_bucket(obs_gain: float) -> int:
    if obs_gain <= -1000.0:
        return 0
    if obs_gain <= -250.0:
        return 1
    if obs_gain <= 0.0:
        return 2
    if obs_gain <= 50.0:
        return 3
    if obs_gain <= 250.0:
        return 4
    if obs_gain <= 1000.0:
        return 5
    return 6


def pack_key(qp: int, sg: int, mg: int, lb: int, lset: int, cost_bin: int, eb: int, cb: int, ob: int) -> int:
    return ((((((((qp * 7 + sg) * 6 + mg) * 4 + lb) * 4 + max(0, min(3, lset)))
               * 32 + max(0, min(31, cost_bin))) * 16 + eb) * 5 + cb) * 7 + ob)


def finite_float(v: str) -> float | None:
    try:
        x = float(v)
    except Exception:
        return None
    return x if math.isfinite(x) else None


def choose_mask(a, max_false_rate: float, max_mean_loss: float) -> int:
    n = a["n"]
    candidates = [
        (1, 2, a["loss1"], a["miss1"]),
        (3, 1, a["loss3"], a["miss3"]),
        (5, 1, a["loss5"], a["miss5"]),
        (7, 0, 0.0, 0),
    ]
    best = (0, float("-inf"), 7)
    for mask, saved, loss, miss in candidates:
        if miss / n <= max_false_rate and loss / n <= max_mean_loss:
            best = max(best, (saved, -loss, mask))
    return best[2]


def mask_contains(mask: int, idx: int) -> bool:
    return (mask & (1 << idx)) != 0


def split_pair(pair: str) -> tuple[str, str]:
    if "|" in pair:
        return tuple(pair.split("|", 1))  # type: ignore[return-value]
    return tuple(pair.split(":", 1))  # type: ignore[return-value]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="+", required=True,
                    help="Pairs in final.csv:decision.csv form. The two files must have matching row order.")
    ap.add_argument("--include-out", type=Path, default=Path("source/Lib/EncoderLib/LardLfnst2ndScoreTable.inc"))
    ap.add_argument("--json-out", type=Path)
    ap.add_argument("--csv-out", type=Path)
    ap.add_argument("--min-samples", type=int, default=20)
    ap.add_argument("--max-false-rate", type=float, default=0.02)
    ap.add_argument("--max-mean-loss", type=float, default=1.0e-4)
    ap.add_argument("--obs-gate", type=float, default=250.0)
    args = ap.parse_args()

    agg = defaultdict(lambda: {
        "n": 0, "c0": 0, "c1": 0, "c2": 0,
        "loss1": 0.0, "loss3": 0.0, "loss5": 0.0,
        "miss1": 0, "miss3": 0, "miss5": 0,
        "gain1": 0.0, "gain2": 0.0,
    })

    total = 0
    for pair in args.pairs:
        final_path_s, decision_path_s = split_pair(pair)
        with open(final_path_s, newline="") as ff, open(decision_path_s, newline="") as df:
            fr = csv.DictReader(ff)
            dr = csv.DictReader(df)
            for frow, drow in zip(fr, dr):
                qp = int(float(frow["qp"]))
                w = int(float(frow["w"]))
                h = int(float(frow["h"]))
                mode = int(float(drow["intraMode"]))
                lset = int(float(drow["lfnstSet"]))
                cost_bin = int(float(frow["dct2CostBin"]))
                dim = 48 if int(float(drow["sbSize"])) > 4 else 16
                input_energy = finite_float(frow["inputEnergy"])
                offdiag = finite_float(frow["offdiagProxy"])
                obs1 = finite_float(frow["obs1"])
                obs2 = finite_float(frow["obs2"])
                c0 = finite_float(frow["cost0"])
                c1 = finite_float(frow["cost1"])
                c2 = finite_float(frow["cost2"])
                if (None in (input_energy, offdiag, obs1, obs2, c0, c1, c2)
                        or c0 <= 0
                        or abs(c0) >= 1.0e100
                        or abs(c1) >= 1.0e100
                        or abs(c2) >= 1.0e100):
                    continue
                costs = [c0, c1, c2]
                best = int(frow["finalLfnstIdx"])
                best_cost = min(costs)
                denom = max(c0, 1.0)
                qs = qstep(qp)
                key = pack_key(
                    qp,
                    size_group(w, h),
                    mode_group(mode),
                    lat_bucket(float(frow["thetaMaxDeg"])),
                    lset,
                    cost_bin,
                    energy_bucket(input_energy / (dim * qs * qs + 1.0e-9)),
                    corr_bucket(offdiag),
                    obs_bucket(max(obs1, obs2)),
                )
                a = agg[key]
                a["n"] += 1
                a[f"c{best}"] += 1
                a["gain1"] += c0 - c1
                a["gain2"] += c0 - c2
                a["loss1"] += max(0.0, c0 - best_cost) / denom
                a["loss3"] += max(0.0, min(c0, c1) - best_cost) / denom
                a["loss5"] += max(0.0, min(c0, c2) - best_cost) / denom
                if best != 0:
                    a["miss1"] += 1
                if best == 2:
                    a["miss3"] += 1
                if best == 1:
                    a["miss5"] += 1
                total += 1

    rows = []
    for key, a in sorted(agg.items()):
        if a["n"] < args.min_samples:
            continue
        mask = choose_mask(a, args.max_false_rate, args.max_mean_loss)
        rows.append({
            "key": key,
            "samples": a["n"],
            "mask": mask,
            "score1": a["gain1"] / a["n"],
            "score2": a["gain2"] / a["n"],
        })

    # In-sample table behavior, with the same obsGate safety as encoder runtime.
    eval_counts = Counter()
    for pair in args.pairs:
        final_path_s, decision_path_s = split_pair(pair)
        with open(final_path_s, newline="") as ff, open(decision_path_s, newline="") as df:
            fr = csv.DictReader(ff)
            dr = csv.DictReader(df)
            table = {r["key"]: r for r in rows}
            for frow, drow in zip(fr, dr):
                qp = int(float(frow["qp"]))
                w = int(float(frow["w"]))
                h = int(float(frow["h"]))
                mode = int(float(drow["intraMode"]))
                lset = int(float(drow["lfnstSet"]))
                cost_bin = int(float(frow["dct2CostBin"]))
                dim = 48 if int(float(drow["sbSize"])) > 4 else 16
                input_energy = finite_float(frow["inputEnergy"])
                offdiag = finite_float(frow["offdiagProxy"])
                obs1 = finite_float(frow["obs1"])
                obs2 = finite_float(frow["obs2"])
                if None in (input_energy, offdiag, obs1, obs2):
                    continue
                qs = qstep(qp)
                key = pack_key(qp, size_group(w, h), mode_group(mode), lat_bucket(float(frow["thetaMaxDeg"])),
                               lset, cost_bin,
                               energy_bucket(input_energy / (dim * qs * qs + 1.0e-9)),
                               corr_bucket(offdiag), obs_bucket(max(obs1, obs2)))
                ent = table.get(key)
                mask = int(ent["mask"]) if ent else 7
                if mask == 1 and max(obs1, obs2) >= args.obs_gate:
                    mask = 7
                final_idx = int(frow["finalLfnstIdx"])
                eval_counts["n"] += 1
                eval_counts[f"final{final_idx}"] += 1
                eval_counts[f"mask{mask}"] += 1
                if not mask_contains(mask, final_idx):
                    eval_counts["miss"] += 1
                    eval_counts[f"miss{final_idx}"] += 1
                if final_idx == 0 and mask != 1:
                    eval_counts["overkeep0"] += 1

    args.include_out.parent.mkdir(parents=True, exist_ok=True)
    with args.include_out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("// Generated by tools/lard_lfnst2nd_fit_score_table.py\n")
        fh.write(f"// totalRows={total}, entries={len(rows)}, minSamples={args.min_samples}, maxFalseRate={args.max_false_rate:g}, maxMeanLoss={args.max_mean_loss:g}\n")
        fh.write("// Key: qp,sizeGroup,modeGroup,thetaMaxBucket,lfnstSet,dct2CostBin,energyNormBucket,offdiagBucket,maxObsBucket\n")
        fh.write("// Fields: packedKey, samples, mask, meanTrueGain1, meanTrueGain2\n")
        for r in rows:
            fh.write("  { %d, %d, %d, %.9g, %.9g },\n" % (r["key"], r["samples"], r["mask"], r["score1"], r["score2"]))
        fh.write("  { 2147483647, 0, 7, 0.0, 0.0 },\n")

    summary = {
        "totalRows": total,
        "entries": len(rows),
        "minSamples": args.min_samples,
        "maxFalseRate": args.max_false_rate,
        "maxMeanLoss": args.max_mean_loss,
        "maskCounts": dict(Counter(r["mask"] for r in rows)),
        "eval": dict(eval_counts),
    }
    if args.json_out:
        args.json_out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if args.csv_out:
        with args.csv_out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["key", "samples", "mask", "score1", "score2"])
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
