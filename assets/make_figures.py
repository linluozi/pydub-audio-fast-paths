"""
Generate the README charts from evidence/*.json.

Design rules applied here:
  * log scale where the range spans more than ~20x (speedups go 1.4x-20.8x)
  * IQR whiskers, not min/max: a single scheduler hiccup must not stretch a bar
  * the A/A noise band is drawn as a shaded reference, so "1.0x" is visible as
    a floor rather than an invisible assumption
  * English labels: CJK glyphs render as tofu boxes on GitHub
"""
import json
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EV = os.path.join(ROOT, 'evidence')

INK = '#2b2119'
PAPER = '#faf6f0'
AMBER = '#c8892b'
TERRA = '#b4552f'
OLIVE = '#6b6b3a'
MUTED = '#8a7a68'
BROWN = '#7d5a3c'

plt.rcParams.update({
    'font.family': 'DejaVu Sans',
    'font.size': 10,
    'axes.edgecolor': INK,
    'axes.labelcolor': INK,
    'text.color': INK,
    'xtick.color': INK,
    'ytick.color': INK,
    'axes.facecolor': PAPER,
    'figure.facecolor': PAPER,
    'savefig.facecolor': PAPER,
})

ORDER = [
    ('load24_7mb', '24-bit load\n1.2 MB', 'load'),
    ('load24_2mb', '24-bit load\n460 KB', 'load'),
    ('silence_60s', 'detect_silence\n60 s', 'silence'),
    ('silence_30s', 'detect_silence\n30 s', 'silence'),
    ('silence_10s', 'detect_silence\n10 s', 'silence'),
    ('amf_30s', 'mono filter\n30 s', 'interleave'),
    ('cdr_30s', 'compressor\n30 s', 'compress'),
    ('cdr_10s', 'compressor\n10 s', 'compress'),
    ('fade_60s', 'fade_in\n60 s', 'fade'),
    ('fade_30s', 'fade_in\n30 s', 'fade'),
]
COLORS = {'load': AMBER, 'silence': TERRA, 'interleave': OLIVE,
          'compress': MUTED, 'fade': BROWN}


def load(name):
    with open(os.path.join(EV, name), encoding='utf-8') as fh:
        return json.load(fh)


def fig_speedup():
    bench = load('benchmark.json')
    aa = load('noise_floor_aa.json')

    labels, medians, lo, hi, colors = [], [], [], [], []
    for key, label, group in ORDER:
        v = bench[key]
        labels.append(label)
        medians.append(v['speedup_ratio_median'])
        iqr = v['speedup_ratio_iqr']
        lo.append(max(v['speedup_ratio_median'] - iqr[0], 0.01))
        hi.append(max(iqr[1] - v['speedup_ratio_median'], 0.01))
        colors.append(COLORS[group])

    aa_lo = min(v['speedup_ratio_iqr'][0] for v in aa.values())
    aa_hi = max(v['speedup_ratio_iqr'][1] for v in aa.values())

    fig, ax = plt.subplots(figsize=(11.0, 5.6))
    x = np.arange(len(labels))
    ax.axhspan(aa_lo, aa_hi, color=OLIVE, alpha=0.22, zorder=0, lw=0)
    ax.axhline(1.0, color=OLIVE, lw=1.0, ls='--', zorder=1)

    bars = ax.bar(x, medians, color=colors, width=0.66, zorder=3,
                  yerr=[lo, hi], error_kw=dict(ecolor=INK, lw=1.0, capsize=3))

    ax.set_yscale('log')
    ax.set_ylim(0.7, 45)
    ax.set_yticks([1, 2, 5, 10, 20])
    ax.set_yticklabels(['1x', '2x', '5x', '10x', '20x'])
    ax.set_xticks(x)
    # Horizontal tick labels: rotated/stacked two-line labels collided at this
    # bar density, and a legend carries the per-bar meaning better than 10 names.
    short = ['24-bit\n1.2 MB', '24-bit\n460 KB', 'silence\n60 s', 'silence\n30 s',
             'silence\n10 s', 'mono flt\n30 s', 'compress\n30 s', 'compress\n10 s',
             'fade\n60 s', 'fade\n30 s']
    ax.set_xticklabels(short, fontsize=9)
    ax.set_xlim(-0.7, len(labels) - 0.3)
    ax.set_ylabel('speedup vs upstream (log scale)')
    ax.set_title('pydub 0.25.1 - measured speedup by workload\n'
                 'interleaved A/B, median of per-round ratios; whiskers = IQR',
                 fontsize=11, pad=14)

    for bar, m in zip(bars, medians):
        ax.annotate('%.1fx' % m, (bar.get_x() + bar.get_width() / 2, m),
                    textcoords='offset points', xytext=(0, 4),
                    ha='center', va='bottom', fontsize=9.5, color=INK, weight='bold')

    # put the A/A note in the empty top-left area instead of on top of the bars
    ax.annotate('A/A control band %.2f-%.2f  (identical code, two copies)'
                % (aa_lo, aa_hi),
                xy=(-0.6, 32), ha='left', va='center', fontsize=8.5, color=OLIVE)

    ax.grid(axis='y', color=MUTED, alpha=0.25, lw=0.6, zorder=1)
    ax.set_axisbelow(True)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    out = os.path.join(HERE, 'speedup.png')
    fig.savefig(out, dpi=170)
    plt.close(fig)
    print('wrote', out)


def fig_memory():
    bench = load('benchmark.json')
    keys = ['cdr_30s', 'cdr_10s', 'silence_60s', 'silence_30s', 'fade_60s',
            'amf_30s', 'load24_7mb']
    labels = ['compressor\n30 s', 'compressor\n10 s', 'detect_silence\n60 s',
              'detect_silence\n30 s', 'fade_in\n60 s', 'mono filter\n30 s',
              '24-bit load\n1.2 MB']
    up = [bench[k]['upstream_peak_rss_mb'] for k in keys]
    pat = [bench[k]['patched_peak_rss_mb'] for k in keys]

    fig, ax = plt.subplots(figsize=(9.6, 4.7))
    x = np.arange(len(keys))
    w = 0.36
    ax.bar(x - w / 2, up, w, label='upstream', color=TERRA, zorder=3)
    ax.bar(x + w / 2, pat, w, label='patched', color=AMBER, zorder=3)

    for xi, (a, b) in enumerate(zip(up, pat)):
        ax.annotate('%d' % a, (xi - w / 2, a), textcoords='offset points',
                    xytext=(0, 3), ha='center', va='bottom', fontsize=8, color=INK)
        ax.annotate('%d' % b, (xi + w / 2, b), textcoords='offset points',
                    xytext=(0, 3), ha='center', va='bottom', fontsize=8, color=INK)
        if a - b >= 15:
            ax.annotate('-%d MB' % (a - b), (xi, max(a, b)), textcoords='offset points',
                        xytext=(0, 20), ha='center', va='bottom',
                        fontsize=8.5, color=TERRA, weight='bold')

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_ylabel('peak RSS (MB)')
    ax.set_ylim(0, 245)
    ax.set_title('Peak resident memory - the compressor held one bytes object per frame',
                 fontsize=11, pad=12)
    ax.legend(frameon=False, loc='upper right', fontsize=9)
    ax.grid(axis='y', color=MUTED, alpha=0.25, lw=0.6, zorder=1)
    ax.set_axisbelow(True)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    out = os.path.join(HERE, 'memory.png')
    fig.savefig(out, dpi=170)
    plt.close(fig)
    print('wrote', out)


def fig_scaling():
    """Absolute time vs input length.

    Deliberately absolute, not a growth factor: both arms are linear in the
    input length (the window size is fixed), so the honest statement is
    "same shape, ~10x lower constant", not "one is asymptotically better".
    """
    bench = load('benchmark.json')
    lengths = [10, 30, 60]
    up = [bench['silence_%ds' % s]['upstream_seconds_median'] for s in lengths]
    pat = [bench['silence_%ds' % s]['patched_seconds_median'] for s in lengths]

    fig, ax = plt.subplots(figsize=(9.6, 4.8))
    ax.plot(lengths, up, 'o-', color=TERRA, lw=2.0, ms=7, label='upstream', zorder=3)
    ax.plot(lengths, pat, 's-', color=AMBER, lw=2.0, ms=7, label='patched', zorder=3)

    for s, a, b in zip(lengths, up, pat):
        ax.annotate('%.2f s' % a, (s, a), textcoords='offset points', xytext=(0, 10),
                    ha='center', va='bottom', fontsize=9, color=TERRA)
        # the patched curve sits near y=0, so its label goes to the side
        ax.annotate('%.2f s' % b, (s, b), textcoords='offset points', xytext=(12, 4),
                    ha='left', va='bottom', fontsize=9, color=AMBER)
        # place the ratio label in the gap between the two curves
        mid = (a + b) / 2.0
        ax.annotate('%.1fx' % (a / b), (s, mid), textcoords='offset points',
                    xytext=(-16, 0), ha='right', va='center', fontsize=9.5,
                    color=INK, weight='bold',
                    bbox=dict(boxstyle='round,pad=0.22', fc=PAPER, ec='none', alpha=0.92))

    ax.set_xlabel('audio length (s, stereo 44.1 kHz)')
    ax.set_ylabel('detect_silence wall clock (s)')
    ax.set_xticks(lengths)
    ax.set_xlim(2, 72)
    ax.set_ylim(-0.16, max(up) * 1.18)
    ax.set_title('detect_silence: same linear shape, ~10x lower constant\n'
                 'one 1 s window per millisecond of audio, seek_step=1',
                 fontsize=11, pad=12)
    ax.legend(frameon=False, loc='upper left', fontsize=9.5)
    ax.grid(color=MUTED, alpha=0.25, lw=0.6, zorder=1)
    ax.set_axisbelow(True)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    out = os.path.join(HERE, 'scaling.png')
    fig.savefig(out, dpi=170)
    plt.close(fig)
    print('wrote', out)


if __name__ == '__main__':
    fig_speedup()
    fig_memory()
    fig_scaling()
