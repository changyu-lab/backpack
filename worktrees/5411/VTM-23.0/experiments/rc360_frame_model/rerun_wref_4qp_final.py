import csv
import subprocess
from pathlib import Path

root = Path('experiments/rc360_frame_model/wref_frame_4qp_aerialcity')
exe = Path('bin/vs16/msvc-19.29/x86_64/release/EncoderApp.exe')
input_yuv = r'I:\Sequences360\low\AerialCity_half_960x480_30Hz_8b_420.yuv'
qps = [27, 32, 37, 42]
common = [
    '-c', 'cfg/encoder_lowdelay_P_vtm.cfg',
    '-i', input_yuv,
    '-wdt', '960', '-hgt', '480', '-fr', '30', '-f', '2',
    '--IntraPeriod=8', '--GOPSize=8',
    '--RateControl=1', '--TargetBitrate=1000000',
    '--RC360FbTc=0', '--RC360CtuExp=1', '--RC360CtuExpMaxStretch=1.2',
    '--MaxDeltaQP=0', '--MaxCuDQPSubdiv=0', '--WaveFrontSynchro=0',
    '--RC360FbTcSearchRange=16', '--RC360FbTcSearchStep=4',
    '--RC360FbTcTauLow=0.35', '--RC360FbTcTauHigh=1.20',
    '--RC360FbTcKappa=0.50', '--RC360FbTcBeta=0.20',
    '--RC360FbTcWMin=0.70', '--RC360FbTcWMax=1.35',
]

def run(cmd, stdout_path):
    with stdout_path.open('w', encoding='utf-8', errors='replace') as fp:
        return subprocess.run(cmd, stdout=fp, stderr=subprocess.STDOUT).returncode

def remove_if_exists(path):
    try: path.unlink()
    except FileNotFoundError: pass

def mean(xs): return sum(xs) / len(xs) if xs else 0.0

summary = []
all_ctu_rows = []
all_trace_rows = []
for qp in qps:
    print(f'QP {qp}: rerun final')
    qdir = root / f'qp{qp}'
    stats = qdir / 'frame_stats.csv'
    ctu = qdir / 'ctu_log.csv'
    stdout = qdir / 'stdout.log'
    trace = qdir / 'frame_trace.csv'
    for p in [ctu, stdout, trace, qdir/'output.bin', qdir/'rec.yuv']:
        remove_if_exists(p)
    cmd = [str(exe), *common, '-q', str(qp), '-b', str(qdir/'output.bin'), '-o', str(qdir/'rec.yuv'), f'--RC360CtuExpFile={ctu}', '--RC360GopFrame=1', '--RC360GopFrameSW=4', '--RC360AlphaF=1.0', '--RC360BetaF=1.0', '--RC360FrameBitMinRatio=0.70', '--RC360FrameBitMaxRatio=1.30', f'--RC360FrameStatsFile={stats}', f'--RC360TraceFile={trace}']
    rc = run(cmd, stdout)
    remove_if_exists(qdir/'rec.yuv')
    if rc != 0:
        raise SystemExit(f'final rerun failed qp={qp}, rc={rc}, see {stdout}')
    with ctu.open(newline='', encoding='utf-8') as fp:
        rows = list(csv.DictReader(fp))
    raw = [float(r['wref_raw_unclipped']) for r in rows]
    rawc = [float(r['wref_raw_clipped']) for r in rows]
    norm = [float(r['wref_norm_from_clipped']) for r in rows]
    final = [float(r['wref_final']) for r in rows]
    summary.append([qp, len(rows), min(raw), mean(raw), max(raw), min(rawc), mean(rawc), max(rawc), min(norm), mean(norm), max(norm), min(final), mean(final), max(final)])
    for r in rows:
        all_ctu_rows.append({'run_qp': qp, **r})
    with trace.open(newline='', encoding='utf-8') as fp:
        for r in csv.DictReader(fp):
            all_trace_rows.append({'run_qp': qp, **r})

with (root / 'wref_summary.csv').open('w', newline='', encoding='utf-8') as fp:
    writer = csv.writer(fp)
    writer.writerow(['qp','retained_ctu_rows','raw_unclipped_min','raw_unclipped_mean','raw_unclipped_max','raw_clipped_min','raw_clipped_mean','raw_clipped_max','norm_from_clipped_min','norm_from_clipped_mean','norm_from_clipped_max','wref_final_min','wref_final_mean','wref_final_max'])
    writer.writerows(summary)
with (root / 'all_ctu_log.csv').open('w', newline='', encoding='utf-8') as fp:
    writer = csv.DictWriter(fp, fieldnames=list(all_ctu_rows[0].keys()))
    writer.writeheader(); writer.writerows(all_ctu_rows)
with (root / 'all_frame_trace.csv').open('w', newline='', encoding='utf-8') as fp:
    writer = csv.DictWriter(fp, fieldnames=list(all_trace_rows[0].keys()))
    writer.writeheader(); writer.writerows(all_trace_rows)
print(root)
