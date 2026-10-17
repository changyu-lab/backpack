"""Reproducible offline inputs for the VTMRC port (not original HPRC code)."""
import argparse
import hashlib
import json
from collections import deque
from pathlib import Path
import numpy as np


def sha(path,limit=None):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        remaining=limit
        while remaining is None or remaining>0:
            b=f.read(1024*1024 if remaining is None else min(1024*1024,remaining))
            if not b:
                if remaining:raise ValueError('source shorter than requested hash prefix')
                break
            h.update(b)
            if remaining is not None:remaining-=len(b)
    return h.hexdigest()


def adaptive_edges(image):
    """Port convention: Gaussian/Sobel/NMS, high=mean+std, low=.4*high.

    This adaptive Canny threshold rule is NOT claimed to be reference[29]'s ACO.
    Horizontal filtering wraps the ERP seam; vertical filtering reflects.
    """
    image = np.asarray(image, dtype=np.float64)
    smooth = sum(w * np.roll(image, s, axis=1) for w, s in zip((1, 4, 6, 4, 1), range(-2, 3))) / 16
    pad = np.pad(smooth, ((2, 2), (0, 0)), mode='reflect')
    smooth = sum(w * pad[i:i + len(image)] for i, w in enumerate((1, 4, 6, 4, 1))) / 16
    p = np.pad(smooth, ((1, 1), (0, 0)), mode='reflect')
    left, right = np.roll(p, 1, axis=1), np.roll(p, -1, axis=1)
    gx = right[:-2] + 2 * right[1:-1] + right[2:] - left[:-2] - 2 * left[1:-1] - left[2:]
    gy = left[2:] + 2 * p[2:] + right[2:] - left[:-2] - 2 * p[:-2] - right[:-2]
    mag = np.hypot(gx, gy)
    direction = ((np.arctan2(gy, gx) * 180 / np.pi + 180 + 22.5) // 45).astype(int) % 4
    padded = np.pad(mag, ((1, 1), (0, 0)), mode='reflect')
    up, down = padded[:-2], padded[2:]
    neighbors = [(np.roll(mag, 1, 1), np.roll(mag, -1, 1)),
                 (np.roll(up, 1, 1), np.roll(down, -1, 1)), (up, down),
                 (np.roll(up, -1, 1), np.roll(down, 1, 1))]
    nms = np.zeros_like(mag)
    for d, (a, b) in enumerate(neighbors):
        keep = (direction == d) & (mag >= a) & (mag >= b)
        nms[keep] = mag[keep]
    positive = nms[nms > 0]
    if not len(positive):
        return np.zeros(image.shape, dtype=bool)
    high = float(positive.mean() + positive.std())
    weak = (nms >= .4 * high) & (nms > 0)
    edges = nms >= high
    queue = deque(zip(*np.nonzero(edges)))
    h, w = image.shape
    while queue:
        y, x = queue.popleft()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                yy, xx = y + dy, (x + dx) % w
                if 0 <= yy < h and weak[yy, xx] and not edges[yy, xx]:
                    edges[yy, xx] = True
                    queue.append((yy, xx))
    return edges


def frame_features(image, reference, edges, reference_edges, ctu, mu_m, mu_s, search):
    h, w = image.shape
    sf, tf = [], []
    for y in range(0, h, ctu):
        for x in range(0, w, ctu):
            ys, xs = np.arange(y, min(y + ctu, h)), np.arange(x, min(x + ctu, w))
            spatial = float(edges[np.ix_(ys, xs)].sum())
            sf.append(spatial)
            if reference is None:
                tf.append(0.)
                continue
            # Zero MV is first, then increasing radius, for deterministic ties.
            candidates = [(dy, dx) for dy in range(-search, search + 1)
                          for dx in range(-search, search + 1)]
            candidates.sort(key=lambda v: (v[0] * v[0] + v[1] * v[1], v))
            best, best_mv = float('inf'), (0, 0)
            sample = image[np.ix_(ys[::4], xs[::4])]
            for dy, dx in candidates:
                ry = np.clip(ys[::4] + dy, 0, h - 1)
                rx = (xs[::4] + dx) % w
                cost = float(np.abs(sample - reference[np.ix_(ry, rx)]).mean())
                if cost < best:
                    best, best_mv = cost, (dy, dx)
            dy, dx = best_mv
            ref_sf = float(reference_edges[np.ix_(np.clip(ys + dy, 0, h - 1), (xs + dx) % w)].sum())
            tf.append(mu_m * np.hypot(dx, dy) + mu_s * abs(spatial - ref_sf))
    return sf, tf


def write_gaze(out, segments, geometry):
    w, h, ctu, depth, frames = geometry
    by_poc = {}
    for source_poc, pocs, paths in segments:
        paths = np.asarray(paths)
        if source_poc < 0 or source_poc >= frames or paths.shape != (49, len(pocs), 2):
            raise ValueError('ScanDMM must provide (49,segment_frames,2) and valid source POC')
        if not np.isfinite(paths).all() or np.any(paths < 0) or np.any(paths > 1):
            raise ValueError('ScanDMM coordinates must be finite in [0,1]')
        for t, poc in enumerate(pocs):
            if not isinstance(poc, int) or poc < 0 or poc >= frames or poc in by_poc:
                raise ValueError('duplicate/out-of-range display POC')
            by_poc[poc] = paths[:, t, :]
    if set(by_poc) != set(range(frames)):
        raise ValueError('trajectory coverage must equal every encoded display POC')
    out.write(f'VGGAZE 1 {w} {h} {ctu} {depth} {frames} 49\n')
    for poc in range(frames):
        for observer, (y, x) in enumerate(by_poc[poc]):
            out.write(f'{poc} {observer} {y:.17g} {x:.17g}\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('features', 'gaze'):
        s = sub.add_parser(name)
        for arg in ('width', 'height', 'ctu', 'bitdepth', 'frames'):
            s.add_argument('--' + arg, type=int, required=True)
        s.add_argument('--output', type=Path, required=True)
        if name == 'features':
            s.add_argument('--input', type=Path, required=True)
            s.add_argument('--input-bitdepth', type=int, choices=(8, 10), default=8)
            s.add_argument('--mu-m', type=float, required=True)
            s.add_argument('--mu-s', type=float, required=True)
            s.add_argument('--search', type=int, default=4)
        else:
            s.add_argument('--manifest', type=Path, required=True,
                           help='JSON segments: [{source_poc,target_pocs,array}], model_sha256, seed, scandmm_commit')
    args = parser.parse_args()
    geometry = (args.width, args.height, args.ctu, args.bitdepth, args.frames)
    if any(v <= 0 for v in geometry) or args.width % 2 or args.height % 2 or args.bitdepth not in (8, 10):
        parser.error('positive geometry, even YUV420 dimensions and bitdepth 8/10 required')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {'geometry': geometry, 'implementation': 'explicit-port-conventions-v1'}
    if args.command == 'gaze':
        manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
        for key in ('model_sha256', 'seed', 'scandmm_commit', 'segments'):
            if key not in manifest:
                raise ValueError('missing manifest provenance: ' + key)
        segments, hashes = [], []
        for entry in manifest['segments']:
            path = args.manifest.parent / entry['array']
            segments.append((entry['source_poc'], entry['target_pocs'], np.load(path, allow_pickle=False)))
            hashes.append({'path': str(path), 'sha256': sha(path)})
        # Validate everything before publishing output.
        import io
        buffer = io.StringIO()
        write_gaze(buffer, segments, geometry)
        args.output.write_text(buffer.getvalue(), encoding='utf-8')
        report.update(manifest=manifest, arrays=hashes, manifest_sha256=sha(args.manifest))
    else:
        if not np.isfinite([args.mu_m, args.mu_s]).all() or min(args.mu_m, args.mu_s, args.search) < 0:
            parser.error('finite nonnegative feature coefficients/search required')
        samples = args.width * args.height
        dtype = np.dtype('u1' if args.input_bitdepth == 8 else '<u2')
        frame_bytes = samples * 3 // 2 * dtype.itemsize
        if args.input.stat().st_size < frame_bytes * args.frames:
            raise ValueError('input is shorter than requested frames')
        previous, previous_edges = None, None
        with args.input.open('rb') as source, args.output.open('w', encoding='utf-8') as out:
            out.write('VGFEATURES 1 ' + ' '.join(map(str, geometry)) + '\n')
            for poc in range(args.frames):
                image = np.frombuffer(source.read(samples * dtype.itemsize), dtype=dtype).reshape(args.height, args.width).astype(float)
                image *= 255. / ((1 << args.input_bitdepth) - 1)
                source.seek((samples // 2) * dtype.itemsize, 1)
                edges = adaptive_edges(image)
                sf, tf = frame_features(image, previous, edges, previous_edges, args.ctu, args.mu_m, args.mu_s, args.search)
                for c, (s, t) in enumerate(zip(sf, tf)):
                    out.write(f'{poc} {c} {s:.17g} {t:.17g}\n')
                previous, previous_edges = image, edges
        report.update(input_sha256=sha(args.input,frame_bytes*args.frames),input_hash_scope='analyzed YUV420 frame prefix', mu_m=args.mu_m, mu_s=args.mu_s,
                      motion_search=args.search, temporal_reference='previous-display-original',
                      aco='port adaptive Canny; original HPRC thresholds not verified')
    report['output_sha256'] = sha(args.output)
    args.output.with_suffix(args.output.suffix + '.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
