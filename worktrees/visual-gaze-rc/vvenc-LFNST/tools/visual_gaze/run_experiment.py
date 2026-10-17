"""Four fixed-QP-derived targets and matched RC ablations; writes raw evidence."""
import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys
import time
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from prepare import sha
from evaluate import bd_rate

SERIAL = ['--Threads=0', '--MaxParallelFrames=0', '--IFP=0', '--TileParallelCtuEnc=0',
          '--Tiles=1x1', '--WaveFrontSynchro=0', '--WppBitEqual=0', '--HrdParametersPresent=0',
          '--SEIBufferingPeriod=0', '--PerceptQPA=0', '--BIM=0', '--MCTF=0', '--LookAhead=0', '--STA=0']


def run(command, log):
    start = time.monotonic()
    with Path(log).open('w',encoding='utf-8') as output:
        result = subprocess.run(list(map(str, command)), stdout=output, stderr=subprocess.STDOUT, text=True)
    if result.returncode:
        raise RuntimeError(Path(log).read_text(encoding='utf-8')[-4000:])
    return time.monotonic() - start


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('encoder', 'input', 'features', 'sphere', 'output'):
        p.add_argument('--' + key, type=Path, required=True)
    p.add_argument('--gaze',type=Path)
    p.add_argument('--modes',type=int,nargs='+',choices=range(4),default=[0,1,2,3])
    p.add_argument('--input-bitdepth',type=int,choices=(8,10),default=8)
    p.add_argument('--decoder', type=Path)
    p.add_argument('--scratch-root',type=Path,help='temporary raw reconstructions, e.g. remote /dev/shm; requires discard')
    p.add_argument('--discard-reconstruction',action='store_true',
                   help='remove generated raw reconstructions after metrics and decoder hash verification; retain bitstreams and evidence')
    p.add_argument('--configuration', choices=('ldp', 'ldb', 'ra'), default='ldp')
    p.add_argument('--config', type=Path, help='override the shipped matched GOP configuration')
    for key in ('width', 'height', 'frames', 'ctu'):
        p.add_argument('--' + key, type=int, required=True)
    p.add_argument('--fps', type=int, default=30)
    p.add_argument('--strength', type=float, required=True)
    p.add_argument('--delay', type=int, default=16)
    p.add_argument('--jobs',type=int,default=1,choices=range(1,5),help='independent QP workers; each encoder remains serial')
    a = p.parse_args()
    a.modes=sorted(set(a.modes))
    if 0 not in a.modes:p.error('--modes must include anchor mode 0')
    if 3 in a.modes and not a.gaze:p.error('mode 3 requires --gaze')
    if a.discard_reconstruction and not a.decoder:
        p.error('--discard-reconstruction requires --decoder for independent reconstruction verification')
    if a.scratch_root and not a.discard_reconstruction:p.error('--scratch-root requires --discard-reconstruction')
    scratch=None
    if a.scratch_root:
        a.scratch_root.mkdir(parents=True,exist_ok=True)
        scratch=tempfile.TemporaryDirectory(prefix='gaze-',dir=a.scratch_root)
    a.encoder = a.encoder.absolute()
    a.output.mkdir(parents=True, exist_ok=True)
    common = [a.encoder, '--preset', 'faster']
    if a.config:
        common += ['-c', a.config]
    elif a.configuration in ('ldp','ldb'):
        common += ['-c', f'cfg/visual_gaze_{a.configuration}16.cfg']
    common += ['-s', f'{a.width}x{a.height}', '-fr', a.fps, '-f', a.frames, '-i', a.input,
               '--CTUSize=' + str(a.ctu), '--InputBitDepth='+str(a.input_bitdepth),'--OutputBitDepth=10'] + SERIAL
    if a.configuration == 'ra':
        common += ['--GOPSize=32', '--PicReordering=1', '--POC0IDR=1', '--DecodingRefreshType=1', '--IntraPeriod=32']
    def run_qp(qp):
        records = []
        fixed = a.output / f'fixed_qp{qp}.vvc'
        fixed_cmd = common + ['-q', qp, '-b', fixed]
        seconds = run(fixed_cmd, fixed.with_suffix('.log'))
        # Target provenance is actual Annex B output bitrate, rounded to bps.
        # File-rate accuracy uses the same basis; NAL debits are reported separately.
        target = round(fixed.stat().st_size * 8 * a.fps / a.frames)
        fixed_record = dict(qp=qp, target_bps=target, fixed_qp_command=list(map(str, fixed_cmd)),
                            fixed_qp_seconds=seconds, fixed_qp_sha256=sha(fixed),
                            target_basis='fixed-QP AnnexB file bytes including start codes, rounded to nearest bps')
        for mode in a.modes:
            prefix = a.output / f'mode{mode}_qp{qp}'
            stream, rec, trace = prefix.with_suffix('.vvc'), prefix.with_suffix('.yuv'), prefix.with_suffix('.rc.csv')
            if scratch:rec=Path(scratch.name)/(prefix.name+'.yuv')
            command = common + ['-b', stream, '-o', rec, '--VTMTargetBitrate=' + str(target),
                                 '--VTMRCTrace=' + str(trace), '--VisualGazeMode=' + str(mode),
                                 '--VisualGazeStrength=' + str(a.strength), '--VisualGazeFeatures=' + str(a.features),
                                 '--VisualGazeTrace=' + str(prefix.with_suffix('.gaze.csv'))]
            if a.gaze:command+=['--VisualGazePoints='+str(a.gaze)]
            seconds = run(command, prefix.with_suffix('.log'))
            metric_path = prefix.with_suffix('.metrics.json')
            metric_command = [sys.executable, str(Path(__file__).with_name('evaluate.py')), '--input', a.input,
                              '--reconstruction', rec, '--trace', trace, '--bitstream',stream, '--width', a.width, '--height', a.height,
                              '--frames', a.frames, '--input-bitdepth',a.input_bitdepth,'--target-bps', target, '--fps', a.fps, '--delay', a.delay,
                              '--sphere', a.sphere, '--output', metric_path]
            run(metric_command, prefix.with_suffix('.metrics.log'))
            metrics = json.loads(metric_path.read_text())
            result = dict(fixed_record, mode=mode, seconds=seconds, command=list(map(str, command)),
                          actual_bps=metrics['actual_bps'],nal_bps=metrics['nal_bps'], quality=metrics['quality_mean_db'],
                          bitrate_error_percent=metrics['bitrate_error_percent'], stream_sha256=sha(stream),
                          trace_sha256=sha(trace), reconstruction_sha256=sha(rec))
            if a.decoder:
                decoded = rec.with_suffix('.decoded.yuv')
                decode_command = [a.decoder, '-b', stream, '-o', decoded]
                run(decode_command, prefix.with_suffix('.decode.log'))
                if sha(decoded) != sha(rec):
                    raise RuntimeError('decoder reconstruction mismatch')
                result['decoder_matches_reconstruction'] = True
                result['decoder_command'] = list(map(str, decode_command))
            if mode == max(a.modes) and qp == 37:
                repeat = prefix.with_suffix('.repeat.vvc')
                repeat_cmd = command.copy()
                repeat_cmd[repeat_cmd.index('-b') + 1] = repeat
                # The same trace paths are intentional: compare captured hashes.
                run(repeat_cmd, prefix.with_suffix('.repeat.log'))
                result['deterministic'] = sha(repeat) == result['stream_sha256'] and sha(trace) == result['trace_sha256']
                if not result['deterministic']:
                    raise RuntimeError('repeated complete-mode encoding differs')
            records.append(result)
            (a.output / f'results.qp{qp}.partial.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
            if a.discard_reconstruction:
                rec.unlink()
                decoded.unlink()
            print(f'QP{qp} mode{mode}: {result["actual_bps"]:.1f} bps, error {result["bitrate_error_percent"]:.3f}%', flush=True)
        return records
    records=[]
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        futures=[pool.submit(run_qp,q) for q in (22,27,32,37)]
        for future in as_completed(futures):
            records.extend(future.result())
            records.sort(key=lambda r:(r['qp'],r['mode']))
            (a.output/'results.partial.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    anchor = [r for r in records if r['mode'] == 0]
    comparisons = []
    for mode in (m for m in a.modes if m!=0):
        rows = [r for r in records if r['mode'] == mode]
        comparison = dict(mode=mode, time_change_percent=(sum(r['seconds'] for r in rows) / sum(r['seconds'] for r in anchor) - 1) * 100)
        for metric in anchor[0]['quality']:
            try:
                comparison[metric + '_bd_rate_percent'] = bd_rate([r['actual_bps'] for r in anchor], [r['quality'][metric] for r in anchor],
                                                                  [r['actual_bps'] for r in rows], [r['quality'][metric] for r in rows])
            except ValueError as error:
                comparison[metric + '_bd_rate_unavailable'] = str(error)
        comparisons.append(comparison)
    report = dict(scope='platform-port experiment; supplied coefficients are not published-paper parameters',
                  configuration=a.configuration, width=a.width, height=a.height, frames=a.frames,
                  f=a.strength, encoder_sha256=sha(a.encoder), features_sha256=sha(a.features),
                  gaze_sha256=sha(a.gaze) if a.gaze else None, results=records, comparisons=comparisons,
                  timing_scope='encoder wall time only; offline feature/ScanDMM time excluded')
    report['raw_reconstructions_retained']=not a.discard_reconstruction
    report['jobs']=a.jobs
    report['modes']=a.modes
    report['input_bitdepth']=a.input_bitdepth
    report['timing_comparable']=a.jobs==1
    report['scratch_root']=str(a.scratch_root) if a.scratch_root else None
    (a.output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if scratch:scratch.cleanup()


if __name__ == '__main__':
    main()
