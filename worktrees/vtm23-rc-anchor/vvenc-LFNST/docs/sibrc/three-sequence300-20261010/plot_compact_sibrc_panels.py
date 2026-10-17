"""Export compact transparent per-frame anchor/SIBRC panels from assessment.json."""
import argparse
import json
import os
from pathlib import Path
import sys

os.environ.setdefault('MPLCONFIGDIR', str(Path(__file__).parent / 'compact-mplconfig'))
sys.dont_write_bytecode = True
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import numpy as np


def generate_panels(assessment, output_dir=None, sequence_label=None, expected_frames=300):
    """Generate 8 PNG/PDF/SVG panels; return a machine-readable validation report."""
    assessment = Path(assessment)
    output = Path(output_dir) if output_dir else assessment.parent / 'panels'
    output.mkdir(parents=True, exist_ok=True)
    points = json.loads(assessment.read_text(encoding='utf-8'))['points']
    targets = sorted({p['target_bps'] for p in points})
    if len(targets) != 4:
        raise ValueError('Expected exactly four rate points')
    report = {'assessment': str(assessment.resolve()), 'sequence': sequence_label,
              'figure_inches': [3.5, 2.4], 'dpi': 600, 'panels': []}
    with plt.rc_context({'font.family': 'Times New Roman', 'font.size': 9,
                         'font.weight': 'normal', 'axes.labelweight': 'normal',
                         'axes.labelsize': 9, 'axes.titlesize': 9,
                         'xtick.labelsize': 8, 'ytick.labelsize': 8,
                         'legend.fontsize': 9, 'pdf.fonttype': 42,
                         'svg.fonttype': 'none', 'axes.linewidth': .6}):
        for metric, ylabel, stem in [('picture_bitrate_bps', 'Frame bitrate (Mbps)', 'frame_bitrate'),
                                      ('picture_y_spsnr', 'S-PSNR (dB)', 'frame_spsnr')]:
            for rate, target in enumerate(targets, 1):
                fig, ax = plt.subplots(figsize=(3.5, 2.4))
                fig.subplots_adjust(left=.17, right=.975, bottom=.18, top=.92)
                series = []
                for token, label, color, linestyle in [('_anchor_', 'Anchor', '#D55E00', ':'),
                                                        ('_full_', 'SIBRC', '#0072B2', '-')]:
                    matches = [p for p in points if p['target_bps'] == target and token in p['name']]
                    if len(matches) != 1:
                        raise ValueError('Expected one {} at target {}'.format(label, target))
                    values = np.asarray(matches[0][metric], dtype=float)
                    if len(values) != expected_frames or not np.all(np.isfinite(values)):
                        raise ValueError('Invalid or incomplete per-frame data')
                    if metric == 'picture_bitrate_bps':
                        if np.any(values <= 0):
                            raise ValueError('Logarithmic bitrate requires positive data')
                        values = values / 1e6
                    ax.plot(np.arange(len(values)), values, color=color, linestyle=linestyle,
                            marker='.', markersize=1.8, linewidth=.65, label=label)
                    series.append({'method': label, 'frames': len(values), 'min': float(values.min()),
                                   'max': float(values.max()), 'first': float(values[0])})
                if metric == 'picture_bitrate_bps':
                    ax.set_yscale('log')
                ax.set_xlim(0, expected_frames)
                ax.set_xticks([0, 50, 100, 150, 200, 250, 300])
                ax.margins(y=.05)
                ax.set_xlabel('Frame', labelpad=2)
                ax.set_ylabel(ylabel, labelpad=2)
                ax.tick_params(which='both', direction='in', top=True, right=True, length=3, width=.6, pad=3)
                ax.tick_params(which='minor', length=1.8)
                for spine in ax.spines.values():
                    spine.set_visible(True)
                ax.grid(True, which='major', color='.88', linewidth=.5)
                ax.set_title('('+chr(96+rate)+') Target {:.3f} Mbps'.format(target/1e6),loc='left',pad=20)
                ax.legend(loc='lower center', bbox_to_anchor=(.5, 1.005), ncol=2,
                          frameon=False, borderaxespad=0, handlelength=2.6,
                          columnspacing=1.2, handletextpad=.4)
                fig.canvas.draw()
                # Validate every sample lies inside the axes, including the first I frame.
                for line in ax.lines:
                    xy = ax.transData.transform(np.column_stack((line.get_xdata(), line.get_ydata())))
                    bounds = ax.get_window_extent()
                    assert np.all((xy[:, 0] >= bounds.x0) & (xy[:, 0] <= bounds.x1))
                    assert np.all((xy[:, 1] >= bounds.y0) & (xy[:, 1] <= bounds.y1))
                assert all(s.get_visible() for s in ax.spines.values())
                assert any(g.get_visible() for g in ax.get_xgridlines())
                assert any(g.get_visible() for g in ax.get_ygridlines())
                filename = '{}_R{}'.format(stem, rate)
                for extension in ('png', 'pdf', 'svg'):
                    fig.savefig(output / (filename + '.' + extension), dpi=600,
                                transparent=True, bbox_inches='tight', pad_inches=.025)
                report['panels'].append({'file': filename, 'target_bps': target, 'metric': metric,
                                         'series': series, 'scale': ax.get_yscale(),
                                         'spines': 'all visible', 'ticks': 'inward on all sides',
                                         'grid': 'original major grid, gray .88, linewidth .5',
                                         'marker': 'original dot, 1.8pt', 'all_samples_inside_axes': True})
                plt.close(fig)
    (output / 'panel_validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('assessment', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--sequence-label')
    parser.add_argument('--expected-frames', type=int, default=300)
    args = parser.parse_args()
    result = generate_panels(args.assessment, args.output_dir, args.sequence_label, args.expected_frames)
    print('Exported {} panels in PNG/PDF/SVG'.format(len(result['panels'])))
