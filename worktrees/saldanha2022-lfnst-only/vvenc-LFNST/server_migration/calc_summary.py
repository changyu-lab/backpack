import csv
import json
import math
import os
import sys

raw_csv = sys.argv[1]
out_dir = sys.argv[2]

def solve4(a, b):
    m = [list(a[i]) + [b[i]] for i in range(4)]
    for i in range(4):
        p = max(range(i, 4), key=lambda r: abs(m[r][i]))
        m[i], m[p] = m[p], m[i]
        div = m[i][i]
        for c in range(i, 5):
            m[i][c] /= div
        for r in range(4):
            if r == i:
                continue
            f = m[r][i]
            for c in range(i, 5):
                m[r][c] -= f * m[i][c]
    return [m[i][4] for i in range(4)]

def polyfit3(x, y):
    a = [[v**3, v**2, v, 1.0] for v in x]
    return solve4(a, y)

def int_poly(c, x):
    return c[0] * x**4 / 4.0 + c[1] * x**3 / 3.0 + c[2] * x**2 / 2.0 + c[3] * x

def bd_rate(anchor, proposed, metric):
    a_sorted = sorted(anchor, key=lambda r: r[metric])
    p_sorted = sorted(proposed, key=lambda r: r[metric])
    ax = [r[metric] for r in a_sorted]
    px = [r[metric] for r in p_sorted]
    min_int = max(min(ax), min(px))
    max_int = min(max(ax), max(px))
    ay = [math.log(r["bitrate_kbps"]) for r in a_sorted]
    py = [math.log(r["bitrate_kbps"]) for r in p_sorted]
    ca = polyfit3(ax, ay)
    cp = polyfit3(px, py)
    avg = (int_poly(cp, max_int) - int_poly(cp, min_int) - int_poly(ca, max_int) + int_poly(ca, min_int)) / (max_int - min_int)
    return (math.exp(avg) - 1.0) * 100.0

rows = []
with open(raw_csv, newline="") as f:
    reader = csv.DictReader(f)
    for r in reader:
        rows.append({
            "sequence": r["sequence"],
            "preset": r["preset"],
            "set": r["set"],
            "qp": int(r["qp"]),
            "total_time_sec": float(r["total_time_sec"]),
            "bitrate_kbps": float(r["bitrate_kbps"]),
            "y_psnr": float(r["y_psnr"]),
            "u_psnr": float(r["u_psnr"]),
            "v_psnr": float(r["v_psnr"]),
            "yuv_psnr": float(r["yuv_psnr"]),
        })

summary = []
per_qp = []
keys = sorted({(r["sequence"], r["preset"]) for r in rows})
for seq, preset in keys:
    items = [r for r in rows if r["sequence"] == seq and r["preset"] == preset]
    anchor = sorted([r for r in items if r["set"] == "anchor"], key=lambda r: r["qp"])
    proposed = sorted([r for r in items if r["set"] == "proposed"], key=lambda r: r["qp"])
    if len(anchor) != 4 or len(proposed) != 4:
        continue
    total_anchor = sum(r["total_time_sec"] for r in anchor)
    total_proposed = sum(r["total_time_sec"] for r in proposed)
    summary.append({
        "sequence": seq,
        "preset": preset,
        "total_anchor_sec": total_anchor,
        "total_proposed_sec": total_proposed,
        "total_time_delta_pct": (total_proposed - total_anchor) / total_anchor * 100.0,
        "bd_rate_y_pct": bd_rate(anchor, proposed, "y_psnr"),
        "bd_rate_yuv_pct": bd_rate(anchor, proposed, "yuv_psnr"),
        "bd_rate_u_pct": bd_rate(anchor, proposed, "u_psnr"),
        "bd_rate_v_pct": bd_rate(anchor, proposed, "v_psnr"),
    })
    by_qp = {r["qp"]: r for r in proposed}
    for a in anchor:
        p = by_qp[a["qp"]]
        per_qp.append({
            "sequence": seq,
            "preset": preset,
            "qp": a["qp"],
            "anchor_time_sec": a["total_time_sec"],
            "proposed_time_sec": p["total_time_sec"],
            "time_delta_pct": (p["total_time_sec"] - a["total_time_sec"]) / a["total_time_sec"] * 100.0,
            "anchor_bitrate_kbps": a["bitrate_kbps"],
            "proposed_bitrate_kbps": p["bitrate_kbps"],
            "anchor_y_psnr": a["y_psnr"],
            "proposed_y_psnr": p["y_psnr"],
            "anchor_yuv_psnr": a["yuv_psnr"],
            "proposed_yuv_psnr": p["yuv_psnr"],
        })

with open(os.path.join(out_dir, "summary_by_sequence_preset.json"), "w") as f:
    json.dump(summary, f, indent=2)
with open(os.path.join(out_dir, "summary_by_sequence_preset.csv"), "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(summary[0].keys()) if summary else [])
    if summary:
        writer.writeheader()
        writer.writerows(summary)
with open(os.path.join(out_dir, "summary_per_qp.csv"), "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(per_qp[0].keys()) if per_qp else [])
    if per_qp:
        writer.writeheader()
        writer.writerows(per_qp)

for r in summary:
    print(r)
