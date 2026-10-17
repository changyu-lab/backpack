"""ERP luma quality, paper buffer convention and four-point BD-rate."""
import argparse
import csv
import json
import math
from pathlib import Path
import numpy as np
from prepare import sha


def buffer_status(bits, target, fps, delay):
    if delay < 1 or target <= 0 or fps <= 0:
        raise ValueError('positive target, fps and decoding delay required')
    prefix = np.cumsum([0] + list(bits))
    # Eq.32 uses frames counted from one; sum i=0..Nf-N0 is inclusive.
    return [n * target / fps - (prefix[n - delay + 1] if n >= delay else 0)
            for n in range(1, len(bits) + 1)]


def round_360lib(position):
    # TGeometry::round, SVIDEO_ROUND_FIX / 13-bit 2D position precision.
    quantized=np.trunc(position*8192+np.where(position>=0,.5,-.5)).astype(np.int64)
    return (quantized+4096-np.where(position>=0,0,1)) >> 13


def sphere_indices(path, width, height):
    with Path(path).open() as f:
        count = int(f.readline())
        coords = np.loadtxt(f)
    if coords.shape != (count, 2) or not np.isfinite(coords).all():
        raise ValueError('expected JVET sphere count followed by latitude/longitude degrees')
    lat, lon = coords.T
    if np.any(abs(lat) > 90) or np.any(abs(lon) > 180):
        raise ValueError('invalid sphere coordinates')
    # 360Lib TSPSNRMetric::sphToCart -> TEquiRect::map3DTo2D.
    lat,lon=np.deg2rad(lat),np.deg2rad(lon)
    sx,sy,sz=np.sin(lon)*np.cos(lat),np.sin(lat),-np.cos(lon)*np.cos(lat)
    length=np.sqrt(sx*sx+sy*sy+sz*sz)
    xp=(np.pi-np.arctan2(sz,sx))*width/(2*np.pi)-.5
    yp=np.arccos(np.clip(sy/length,-1,1))*height/np.pi-.5
    x=np.clip(round_360lib(xp),0,width-1)
    y=np.clip(round_360lib(yp),0,height-1)
    return y, x


def quality(original, reconstruction, peak, sphere=None):
    error = (np.asarray(original, dtype=float) - reconstruction) ** 2
    h, w = error.shape
    weights = np.sin((np.arange(h) + .5) * np.pi / h)
    mse = {'psnr': float(error.mean()),
           'ws_psnr': float((error.mean(axis=1) * weights).sum() / weights.sum())}
    if sphere is not None:
        mse['s_psnr_nn'] = float(error[sphere].mean())
    return {k: (10 * math.log10(peak * peak / v) if v > 0 else float('inf')) for k, v in mse.items()}


def bd_rate(anchor_rates, anchor_quality, proposal_rates, proposal_quality):
    def curve(rates, values):
        r, q = np.asarray(rates, dtype=float), np.asarray(values, dtype=float)
        if len(r) < 4 or len(r) != len(q) or not np.isfinite(r).all() or not np.isfinite(q).all() or np.any(r <= 0):
            raise ValueError('four finite positive RD points required')
        order = np.argsort(q)
        r, q = r[order], q[order]
        if np.any(np.diff(q) <= 0) or np.any(np.diff(r) <= 0):
            raise ValueError('RD curves must be strictly monotonic')
        return np.polynomial.Polynomial.fit(q, np.log(r), 3).convert(), q
    a, aq = curve(anchor_rates, anchor_quality)
    p, pq = curve(proposal_rates, proposal_quality)
    lo, hi = max(aq.min(), pq.min()), min(aq.max(), pq.max())
    if hi <= lo:
        raise ValueError('RD curves have no quality overlap')
    integral = (p - a).integ()
    return float(np.expm1((integral(hi) - integral(lo)) / (hi - lo)) * 100)


def read_luma(path, width, height, depth, frames):
    dtype = np.dtype('u1' if depth == 8 else '<u2')
    samples = width * height
    with Path(path).open('rb') as f:
        for _ in range(frames):
            data = f.read(samples * dtype.itemsize)
            if len(data) != samples * dtype.itemsize:
                raise ValueError('short YUV reconstruction/source')
            yield np.frombuffer(data, dtype=dtype).reshape(height, width).astype(float)
            f.seek(samples // 2 * dtype.itemsize, 1)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('input', 'reconstruction', 'trace', 'bitstream', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    for name in ('width', 'height', 'frames'):
        p.add_argument('--' + name, type=int, required=True)
    p.add_argument('--input-bitdepth', type=int, choices=(8, 10), default=8)
    p.add_argument('--reconstruction-bitdepth', type=int, choices=(8, 10), default=10)
    p.add_argument('--target-bps', type=float, required=True)
    p.add_argument('--fps', type=float, required=True)
    p.add_argument('--delay', type=int, required=True)
    p.add_argument('--sphere', type=Path)
    a = p.parse_args()
    sphere = sphere_indices(a.sphere, a.width, a.height) if a.sphere else None
    original = read_luma(a.input, a.width, a.height, a.input_bitdepth, a.frames)
    rec = read_luma(a.reconstruction, a.width, a.height, a.reconstruction_bitdepth, a.frames)
    per_frame = []
    for raw, reconstruction in zip(original, rec):
        raw *= 2. ** (a.reconstruction_bitdepth - a.input_bitdepth)
        per_frame.append(quality(raw, reconstruction, 255 << (a.reconstruction_bitdepth-8), sphere))
    with a.trace.open() as f:
        coded = [r for r in csv.DictReader(f) if r['event'] == 'picture']
        pictures = sorted(coded, key=lambda r: int(r['poc']))
    if len(pictures) != a.frames or [int(r['poc']) for r in pictures] != list(range(a.frames)):
        raise ValueError('VTMRC trace POC coverage mismatch')
    bits = [int(r['bits']) for r in pictures]
    nal_bitrate = sum(bits) * a.fps / a.frames
    bitrate = a.bitstream.stat().st_size*8*a.fps/a.frames
    report = dict(actual_bps=bitrate, target_bps=a.target_bps,
                  bitrate_error_percent=abs(bitrate / a.target_bps - 1) * 100,
                  actual_bps_basis='AnnexB file bytes, same basis as fixed-QP targets',
                  nal_bps=nal_bitrate,nal_bitrate_error_percent=abs(nal_bitrate/a.target_bps-1)*100,
                  quality_mean_db={k: float(np.mean([v[k] for v in per_frame])) for k in per_frame[0]},
                  frames=per_frame, frame_bits_display_order=bits,
                  buffer_encoding_order=buffer_status([int(r['bits']) for r in coded], a.target_bps, a.fps, a.delay),
                  encoding_pocs=[int(r['poc']) for r in coded],
                  buffer_delay=a.delay, buffer_convention='Eq32 inclusive sum, encoding-order debit',
                  sphere_sha256=sha(a.sphere) if a.sphere else None,
                  metric_scope='ERP luma; 360Lib sphere orientation, 8192 rounding, peak=255<<(depth-8); S-PSNR-NN only, no S-PSNR-I claim',
                  input_sha256=sha(a.input,a.width*a.height*3//2*(1 if a.input_bitdepth==8 else 2)*a.frames),
                  input_hash_scope='evaluated YUV420 frame prefix, including chroma',
                  reconstruction_sha256=sha(a.reconstruction), trace_sha256=sha(a.trace),bitstream_sha256=sha(a.bitstream))
    a.output.write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
