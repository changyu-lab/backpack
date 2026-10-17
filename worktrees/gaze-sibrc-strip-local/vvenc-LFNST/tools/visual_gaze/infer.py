"""Run the pinned official ScanDMM model on display-GOP source images.

Requires a CUDA PyTorch environment; extra dependencies can be installed with
--target external/pydeps. No author source/model files are modified.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
from prepare import sha


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', type=Path, required=True)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--width', type=int, required=True)
    p.add_argument('--height', type=int, required=True)
    p.add_argument('--frames', type=int, required=True)
    p.add_argument('--gop', type=int, choices=(16, 32), required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seed', type=int, default=1234)
    p.add_argument('--resize', type=int, nargs=2, metavar=('W', 'H'),
                   help='also save downsampled 8bit YUV420 for a software smoke experiment')
    a = p.parse_args()
    import cv2
    import numpy as np
    import pyro
    import torch
    sys.path.insert(0, str(a.repo.absolute()))
    from models import DMM
    from inference import Inference
    if not torch.cuda.is_available():
        raise RuntimeError('Official inference.py requires CUDA; no synthetic gaze substitute')
    if min(a.width, a.height, a.frames) <= 0 or a.width % 2 or a.height % 2:
        raise ValueError('positive even YUV420 geometry required')
    model_path = a.repo / 'model/model_lr-0.0003_bs-64_epoch-435.pkl'
    commit = subprocess.check_output(['git', '-C', str(a.repo), 'rev-parse', 'HEAD'], text=True).strip()
    pyro.set_rng_seed(a.seed)
    random.seed(a.seed)
    np.random.seed(a.seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    model = DMM(use_cuda=True)
    model.load_state_dict(torch.load(model_path, map_location='cuda'))
    model.eval()
    a.output.mkdir(parents=True, exist_ok=True)
    segments, source_hash = [], hashlib.sha256()
    size = a.width * a.height
    if a.resize and (min(a.resize) <= 0 or any(v % 2 for v in a.resize)):
        raise ValueError('resize must have positive even dimensions')
    downsampled = (a.output / 'smoke.yuv').open('wb') if a.resize else None
    try:
        with a.input.open('rb') as f:
            for poc in range(a.frames):
                raw = f.read(size * 3 // 2)
                if len(raw) != size * 3 // 2:
                    raise ValueError('short 8bit YUV420 source')
                source_hash.update(raw)
                planes = [np.frombuffer(raw[:size], dtype=np.uint8).reshape(a.height, a.width),
                          np.frombuffer(raw[size:size * 5 // 4], dtype=np.uint8).reshape(a.height // 2, a.width // 2),
                          np.frombuffer(raw[size * 5 // 4:], dtype=np.uint8).reshape(a.height // 2, a.width // 2)]
                if downsampled:
                    for i, plane in enumerate(planes):
                        w, h = a.resize
                        if i:
                            w, h = w // 2, h // 2
                        downsampled.write(cv2.resize(plane, (w, h), interpolation=cv2.INTER_AREA).tobytes())
                if poc % a.gop:
                    continue
                length = min(a.gop, a.frames - poc)
                image_dir = a.output / f'images_{poc}'
                array_dir = a.output / f'paths_{poc}'
                image_dir.mkdir(exist_ok=True)
                # Explicit RGB conversion convention: BT709 limited-range YUV.
                y = (planes[0].astype(float) - 16) / 219
                u = (cv2.resize(planes[1], (a.width, a.height), interpolation=cv2.INTER_LINEAR).astype(float) - 128) / 224
                v = (cv2.resize(planes[2], (a.width, a.height), interpolation=cv2.INTER_LINEAR).astype(float) - 128) / 224
                rgb = np.stack((y + 1.5748 * v, y - .187324 * u - .468124 * v, y + 1.8556 * u), axis=-1)
                bgr = np.clip(np.rint(rgb[:, :, ::-1] * 255), 0, 255).astype(np.uint8)
                image = image_dir / f'poc_{poc}.png'
                if not cv2.imwrite(str(image), bgr):
                    raise RuntimeError('could not save ScanDMM input image')
                Inference(model, str(image_dir), 49, length, str(array_dir), if_plot=False).predict()
                array = array_dir / f'poc_{poc}.npy'
                shape = np.load(array, allow_pickle=False).shape
                if shape != (49, length, 2):
                    raise ValueError('unexpected official inference shape: ' + str(shape))
                segments.append(dict(source_poc=poc, target_pocs=list(range(poc, poc + length)),
                                     array=str(array.relative_to(a.output)), image_sha256=sha(image)))
    finally:
        if downsampled:
            downsampled.close()
    manifest = dict(model_sha256=sha(model_path), seed=a.seed, scandmm_commit=commit,gop=a.gop,
                    torch=torch.__version__, pyro=pyro.__version__, numpy=np.__version__,
                    model_eval=True, source_prefix_sha256=source_hash.hexdigest(),
                    source_geometry=[a.width, a.height], source_frames=a.frames,
                    segment_convention='display GOP starts at POC0; no additional I frames inserted',
                    image_conversion='8bit YUV420 BT709 limited range; bilinear chroma upsample',
                    resize=a.resize, segments=segments)
    (a.output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Saved official ScanDMM manifest', a.output / 'manifest.json', flush=True)


if __name__ == '__main__':
    main()
