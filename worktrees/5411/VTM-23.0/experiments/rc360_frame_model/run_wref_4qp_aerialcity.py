import csv
import shutil
import subprocess
from pathlib import Path

root = Path('experiments/rc360_frame_model/wref_frame_4qp_aerialcity')
if root.exists():
    shutil.rmtree(root)
root.mkdir(parents=True, exist_ok=True)
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
    try:
        path.unlink()
    except FileNotFoundError:
        pass

def mean(xs, fallback=1.0):
    return sum(xs) / len(xs) if xs else fallback

def make_stats(ctu_csv, stats_csv):
    by_poc = {}
    with ctu_csv.open(newline='', encoding='utf-8') as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            poc = int(row['poc'])
            d = by_poc.setdefault(poc, {'ieff': [], 'raw_unclip': [], 'raw_clip': [], 'final': []})
            d['ieff'].append(float(row.get('ieff_raw', '0') or 0.0))
            d['raw_unclip'].append(float(row.get('frame_wref_raw_unclipped', row.get('wref_raw_unclipped', '1')) or 1.0))
            d['raw_clip'].append(float(row.get('frame_wref_raw_clipped', row.get('wref_raw_clipped', '1')) or 1.0))
            d['final'].append(float(row.get('frame_wref_final_mean', row.get('wref_final', '1')) or 1.0))
    with stats_csv.open('w', newline='', encoding='utf-8') as fp:
        writer = csv.writer(fp)
        writer.writerow(['poc','ieff','wref','frame_wref_raw_unclipped','frame_wref_raw_clipped','frame_wref_final'])
        for poc in sorted(by_poc):
            d = by_poc[poc]
            ieff = mean(d['ieff'], 0.0)
            raw_unclip = mean(d['raw_unclip'])
            raw_clip = mean(d['raw_clip'])
            final = mean(d['final'])
            writer.writerow([poc, f'{ieff:.12g}', f'{raw_clip:.12g}', f'{raw_unclip:.12g}', f'{raw_clip:.12g}', f'{final:.12g}'])

summary = []
all_ctu_rows = []
all_trace_rows = []
for qp in qps:
    print(f'QP {qp}: prepass')
    qdir = root / f'qp{qp}'
    qdir.mkdir(parents=True, exist_ok=True)
    pre_ctu = qdir / 'pre_ctu_log.csv'
    pre_stdout = qdir / 'pre_stdout.log'
    pre_bin = qdir / 'pre_output.bin'
    pre_rec = qdir / 'pre_rec.yuv'
    cmd = [str(exe), *common, '-q', str(qp), '-b', str(pre_bin), '-o', str(pre_rec), f'--RC360CtuExpFile={pre_ctu}', '--RC360GopFrame=0']
    rc = run(cmd, pre_stdout)
    remove_if_exists(pre_rec)
    if rc != 0:
        raise SystemExit(f'prepass failed qp={qp}, rc={rc}, see {pre_stdout}')
    stats = qdir / 'frame_stats.csv'
    make_stats(pre_ctu, stats)

    print(f'QP {qp}: final run')
    ctu = qdir / 'ctu_log.csv'
    stdout = qdir / 'stdout.log'
    trace = qdir / 'frame_trace.csv'
    out_bin = qdir / 'output.bin'
    rec = qdir / 'rec.yuv'
    cmd = [str(exe), *common, '-q', str(qp), '-b', str(out_bin), '-o', str(rec), f'--RC360CtuExpFile={ctu}', '--RC360GopFrame=1', '--RC360GopFrameSW=4', '--RC360AlphaF=1.0', '--RC360BetaF=1.0', '--RC360FrameBitMinRatio=0.70', '--RC360FrameBitMaxRatio=1.30', f'--RC360FrameStatsFile={stats}', f'--RC360TraceFile={trace}']
    rc = run(cmd, stdout)
    remove_if_exists(rec)
    if rc != 0:
        raise SystemExit(f'final run failed qp={qp}, rc={rc}, see {stdout}')

    with ctu.open(newline='', encoding='utf-8') as fp:
        rows = list(csv.DictReader(fp))
    raw = [float(r['wref_raw_unclipped']) for r in rows]
    rawc = [float(r['wref_raw_clipped']) for r in rows]
    norm = [float(r['wref_norm_from_clipped']) for r in rows]
    final = [float(r['wref_final']) for r in rows]
    summary.append([qp, len(rows), min(raw), mean(raw), max(raw), min(rawc), mean(rawc), max(rawc), min(norm), mean(norm), max(norm), min(final), mean(final), max(final)])
    for r in rows:
        rr = {'run_qp': qp, **r}
        all_ctu_rows.append(rr)
    with trace.open(newline='', encoding='utf-8') as fp:
        for r in csv.DictReader(fp):
            rr = {'run_qp': qp, **r}
            all_trace_rows.append(rr)

with (root / 'wref_summary.csv').open('w', newline='', encoding='utf-8') as fp:
    writer = csv.writer(fp)
    writer.writerow(['qp','retained_ctu_rows','raw_unclipped_min','raw_unclipped_mean','raw_unclipped_max','raw_clipped_min','raw_clipped_mean','raw_clipped_max','norm_from_clipped_min','norm_from_clipped_mean','norm_from_clipped_max','wref_final_min','wref_final_mean','wref_final_max'])
    writer.writerows(summary)

if all_ctu_rows:
    with (root / 'all_ctu_log.csv').open('w', newline='', encoding='utf-8') as fp:
        writer = csv.DictWriter(fp, fieldnames=list(all_ctu_rows[0].keys()))
        writer.writeheader(); writer.writerows(all_ctu_rows)
if all_trace_rows:
    with (root / 'all_frame_trace.csv').open('w', newline='', encoding='utf-8') as fp:
        writer = csv.DictWriter(fp, fieldnames=list(all_trace_rows[0].keys()))
        writer.writeheader(); writer.writerows(all_trace_rows)
print(root)
