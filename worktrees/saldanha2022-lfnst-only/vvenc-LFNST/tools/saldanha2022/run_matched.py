"""Matched Saldanha retraining experiment; never applies Stage123 acceptance gates."""
from __future__ import annotations
import argparse
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
QPS = [22, 27, 32, 37]

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()

def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, default=str, allow_nan=False), encoding='utf-8')
    tmp.replace(path)

def arm_environment(base, kind, model, stats, sequence):
    env = {k: v for k, v in base.items() if not k.startswith('SALDANHA_')}
    env.update(SALDANHA_MODE={'anchor': 'off', 'proposed': 'on'}[kind],
               SALDANHA_MODEL=str(model), SALDANHA_STATS=str(stats), SALDANHA_SEQUENCE=sequence)
    return env

def provenance_matches(saved, expected):
    return saved == expected

def validate_stats(stats, kind):
    for key in ('eligible', 'predicted_skip', 'suppressed_candidates'):
        if type(stats.get(key)) is not int or stats[key] < 0:
            raise ValueError('Missing/invalid Saldanha statistic: '+key)
    if stats['predicted_skip'] > stats['eligible']:
        raise ValueError('Predicted skips exceed eligible decisions')
    if kind == 'proposed' and stats['eligible'] == 0:
        raise ValueError('No eligible proposed decisions; intervention unverified')

def load_reference(root):
    root = Path(root).resolve()
    expected = json.loads((HERE / 'reference_hashes.json').read_text())
    actual = {name: sha(root / name) for name in expected}
    if actual != expected:
        raise ValueError('Reference snapshot hash mismatch')
    sys.path.insert(0, str(root))
    module = importlib.import_module('tools.lard_lfnst.run_skip21_stage12_ra_360lib')
    if Path(module.__file__).resolve() != root / 'tools/lard_lfnst/run_skip21_stage12_ra_360lib.py':
        raise ValueError('Unexpected reference module import location')
    return module, actual

def summarize(rows, qps, repeats, legacy):
    expected = {(qp, rep, kind) for qp in qps for rep in range(1, repeats+1) for kind in ('anchor', 'proposed')}
    found = {(r['QP'], r['repeat'], r['kind']) for r in rows}
    result = {'complete': found == expected and len(rows) == len(expected), 'bd_rate': None}
    if not result['complete']:
        result['missing'] = sorted(expected - found)
        return result
    result['timing'] = legacy.summarize_timing(rows)
    result['TSbest_pct'] = result['timing']['overall']['max_TS_pct']
    result['TSmedian_pct'] = result['timing']['overall']['median_TS_pct']
    try:
        result['bd_rate'] = legacy.compute_official_bdbr(rows, qps)
    except ValueError as exc:
        result['bd_rate_error'] = str(exc)
    return result

def complete(case, legacy):
    manifest = Path(case['directory']) / 'result.json'
    if not manifest.exists():
        return None
    try:
        result = json.loads(manifest.read_text())
        if not provenance_matches(result['provenance'], case):
            raise ValueError('stale provenance')
        required = {'stream.vvc', 'encode.log', 'metrics.json', '360lib.log'}
        if case['kind'] == 'proposed':
            required.add('stats.json')
            validate_stats(json.loads((Path(case['directory'])/'stats.json').read_text()), 'proposed')
        if set(result['artifact_hashes']) != required:
            raise ValueError('Incomplete artifact hash manifest')
        for key, digest in result['artifact_hashes'].items():
            if sha(Path(case['directory']) / key) != digest:
                raise ValueError('artifact hash changed')
        if not legacy._official_metrics_are_valid(result['official_metrics'], case['frames']):
            raise ValueError('incomplete official metrics')
        for name in ('Kbps', 'Seconds'):
            if not math.isfinite(result[name]) or result[name] <= 0:
                raise ValueError('invalid ' + name)
        return result
    except (KeyError, ValueError, OSError, TypeError) as exc:
        raise ValueError(f'Refusing stale/incomplete case {manifest}: {exc}; use a fresh output directory') from exc

def admit(min_free_gib):
    if os.name == 'nt':
        import ctypes
        class Memory(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [(n, ctypes.c_ulonglong) for n in ('total', 'available', 'page_total', 'page_available', 'virtual_total', 'virtual_available', 'extended')]
        status = Memory()
        status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise RuntimeError('Cannot determine available memory')
        if status.available < min_free_gib * 1024**3:
            raise RuntimeError(f'Insufficient free memory: {status.available / 1024**3:.2f} GiB')

def run_case(case, legacy, args):
    previous = complete(case, legacy)
    if previous:
        return previous
    directory = Path(case['directory'])
    if directory.exists() and any(directory.iterdir()):
        raise ValueError(f'Incomplete case retained at {directory}; use a fresh output directory')
    admit(args.min_free_gib)
    directory.mkdir(parents=True, exist_ok=True)
    write(directory / 'case.json', case)
    env = arm_environment(os.environ, case['kind'], args.model, directory/'stats.json', case['sequence'])
    start = time.perf_counter()
    with (directory/'encode.log').open('w', encoding='utf-8') as log:
        subprocess.run(case['command'], env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    seconds = time.perf_counter() - start
    if case['kind'] == 'proposed':
        validate_stats(json.loads((directory/'stats.json').read_text()), 'proposed')
    bitrate, *_ = legacy.parse_log(directory/'encode.log')
    seq = case['seq']
    official = legacy.run_360lib_metrics(executable=args.convert360, original=Path(seq['path']),
        reconstruction=directory/'reconstruction.yuv', sphere_file=args.sphere,
        width=seq['width'], height=seq['height'], fps=seq['fps'], frames=case['frames'],
        original_bitdepth=seq['bitdepth'], reconstruction_bitdepth=10,
        log_path=directory/'360lib.log', parsed_json_path=directory/'metrics.json')
    result = {'provenance': case, 'QP': case['QP'], 'repeat': case['repeat'], 'kind': case['kind'],
        'Seconds': seconds, 'Kbps': bitrate, 'official_metrics': official, **official,
        'artifact_hashes': {name: sha(directory/name) for name in
            ['stream.vvc', 'encode.log', 'metrics.json', '360lib.log'] + (['stats.json'] if case['kind'] == 'proposed' else [])}}
    write(directory/'result.json', result)
    complete(case, legacy)
    rec = (directory/'reconstruction.yuv').resolve()
    if rec.parent != directory.resolve() or not rec.is_relative_to(args.output):
        raise ValueError('Unsafe reconstruction cleanup path')
    rec.unlink()
    return result

def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('encoder', 'model', 'seq-root', 'output', 'sphere', 'reference-runner-root'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--360convert', dest='convert360', type=Path, required=True)
    p.add_argument('--configs', default='AI,RA,LD')
    p.add_argument('--sequences', default='', help='comma-separated exact parsed names')
    p.add_argument('--qps', default='22,27,32,37')
    p.add_argument('--repeats', type=int, default=2)
    p.add_argument('--threads', type=int, default=32)
    p.add_argument('--preset', default='medium')
    p.add_argument('--min-free-gib', type=float, default=8)
    p.add_argument('--dry-run', action='store_true')
    return p

def main(argv=None):
    args = parser().parse_args(argv)
    for name in ('encoder', 'model', 'seq_root', 'output', 'sphere', 'reference_runner_root', 'convert360'):
        setattr(args, name, getattr(args, name).resolve())
    legacy, reference_hashes = load_reference(args.reference_runner_root)
    qps = [int(v) for v in args.qps.split(',')]
    if qps != QPS or args.repeats != 2 or args.threads != 32 or args.preset != 'medium':
        raise ValueError('Matched formal protocol requires QPs 22,27,32,37, repeats 2, threads 32, preset medium')
    hashes = {name+'_sha256': sha(getattr(args, name)) for name in ('encoder', 'model', 'sphere', 'convert360')}
    hashes['reference_hashes'] = reference_hashes
    hashes['runner_sha256'] = sha(__file__)
    selection = set(filter(None, args.sequences.split(',')))
    seqs = [legacy.parse_sequence(p) for p in sorted(args.seq_root.glob('*.yuv'))]
    if selection:
        seqs = [s for s in seqs if s['name'] in selection]
        if {s['name'] for s in seqs} != selection:
            raise ValueError('Requested sequence missing')
    if not seqs:
        raise ValueError('No sequences found')
    cases = []
    for config in args.configs.split(','):
        frames = legacy.frames_for_config(config, ra_gop=16, ld_gop=8, ai_frames=1)
        for seq in seqs:
            if seq['available_frames'] < frames:
                raise ValueError('Insufficient frames: '+seq['name'])
            seq = {**seq, 'path': str(seq['path'])}
            source_stat = Path(seq['path']).stat()
            for qp in qps:
                for repeat, kind in legacy.paired_schedule(args.repeats):
                    d = args.output/config/seq['name']/f'QP{qp}'/f'repeat{repeat}'/kind
                    cmd = legacy.build_encoder_command(encoder=args.encoder, seq=seq, qp=qp, frames=frames,
                        encode_config=config, ra_gop=16, ld_gop=8, threads=args.threads, preset=args.preset,
                        additional=legacy.ANCHOR_ADDITIONAL, bitstream=d/'stream.vvc', reconstruction=d/'reconstruction.yuv')
                    env = arm_environment({}, kind, args.model, d/'stats.json', seq['name'])
                    cases.append(dict(directory=str(d), sequence=seq['name'], seq=seq, config=config, QP=qp,
                        repeat=repeat, kind=kind, frames=frames, command=cmd, environment=env,
                        unset_environment=['SALDANHA_CSV'], hashes=hashes,
                        source_identity={'size': source_stat.st_size, 'mtime_ns': source_stat.st_mtime_ns}))
    plan = dict(protocol='Saldanha retrained VVenC matched formal', hashes=hashes, cases=cases,
                source_identity_policy='path, size, mtime_ns; source YUV is not content-hashed', concurrent_encoder_jobs=1)
    if args.dry_run:
        write(args.output/'plan.json', plan)
        print(json.dumps(plan, indent=2))
        return 0
    args.output.mkdir(parents=True, exist_ok=True)
    lock = args.output/'runner.lock'
    with lock.open('x') as f:
        f.write(str(os.getpid()))
    try:
        write(args.output/'plan.json', plan)
        groups = {}
        for index, case in enumerate(cases, 1):
            result = run_case(case, legacy, args)
            key = case['config']+'/'+case['sequence']
            groups.setdefault(key, []).append(result)
            write(args.output/'summary.json', {k: summarize(v, qps, args.repeats, legacy) for k,v in groups.items()})
            progress = {'completed': index, 'total': len(cases), 'last_case': case['directory']}
            write(args.output/'progress.json', progress)
            print(json.dumps(progress), flush=True)
    finally:
        lock.unlink()
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
