"""
plot_trajectories — trajectory figures for one or multiple trial CSVs.

Single trial  → 3-subplot PDF (RULA score / upper-arm / TCP Z vs time).
Multiple trials → one PDF page per trial, plus a final summary overlay page.

Usage:
  python3 plot_trajectories.py --csv /tmp/trial.csv --out figures/trial.pdf
  python3 plot_trajectories.py --csv /tmp/trial_*.csv --out figures/all_trials.pdf
"""

import argparse
import csv
import glob
import math
import os
import sys

import numpy as np

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
except ImportError:
    print('ERROR: matplotlib is required.  pip install matplotlib')
    sys.exit(1)

FIG_W_MM = 170      # full A4 width for readability
FIG_H_MM = 200
MM_TO_IN = 1 / 25.4
FONT_SIZE = 8

plt.rcParams.update({
    'font.size':        FONT_SIZE,
    'axes.labelsize':   FONT_SIZE,
    'xtick.labelsize':  FONT_SIZE - 1,
    'ytick.labelsize':  FONT_SIZE - 1,
    'legend.fontsize':  FONT_SIZE - 1,
    'lines.linewidth':  0.9,
    'axes.linewidth':   0.5,
    'grid.linewidth':   0.3,
    'pdf.fonttype':     42,
    'ps.fonttype':      42,
})

COLOR_R   = '#d62728'
COLOR_L   = '#1f77b4'
ALPHA_RAW = 0.20
EMA_ALPHA = 0.10


def load_csv(path):
    with open(path, newline='') as f:
        return list(csv.DictReader(f))


def to_f(v):
    try:    return float(v)
    except: return float('nan')


def to_i(v):
    try:    return int(v)
    except: return -1


def ema(arr, alpha=EMA_ALPHA):
    out = np.empty_like(arr, dtype=float)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return out


def find_event_rows(rows, keyword):
    return [(i, to_f(r['timestamp_s'])) for i, r in enumerate(rows)
            if keyword in r.get('phase_event', '')]


def load_trial(path):
    rows = load_csv(path)
    if not rows:
        return None
    t      = np.array([to_f(r['timestamp_s'])        for r in rows])
    r_rula = np.array([to_i(r['right_rula_score'])   for r in rows], dtype=float)
    l_rula = np.array([to_i(r['left_rula_score'])    for r in rows], dtype=float)
    r_ua   = np.array([to_f(r['right_arm_up'])       for r in rows])
    l_ua   = np.array([to_f(r['left_arm_up'])        for r in rows])
    r_la   = np.array([to_f(r['right_low_angle'])    for r in rows])
    l_la   = np.array([to_f(r['left_low_angle'])     for r in rows])
    tcp_z  = np.array([to_f(r['tcp_z_m'])            for r in rows])

    opt_events = find_event_rows(rows, 'RULA_OPTIMIZING')
    adj_events = find_event_rows(rows, 'USER_ADJUSTMENT')
    phase_lines = ([(ts, 'OPT') for _, ts in opt_events] +
                   [(ts, 'Conv') for _, ts in adj_events])

    return dict(path=path, t=t, r_rula=r_rula, l_rula=l_rula,
                r_ua=r_ua, l_ua=l_ua, r_la=r_la, l_la=l_la,
                tcp_z=tcp_z, phase_lines=phase_lines)


def plot_trial(d, fig, axes, title):
    t0    = d['t'][0]
    t_rel = d['t'] - t0

    ax = axes[0]
    ax.set_title(title, fontsize=FONT_SIZE, pad=3)
    ax.axhspan(0,   2.5, color='#2ca02c', alpha=0.10, zorder=0)
    ax.axhspan(2.5, 4.5, color='#ffff00', alpha=0.12, zorder=0)
    ax.axhspan(4.5, 6.5, color='#ff7f0e', alpha=0.12, zorder=0)
    ax.axhspan(6.5, 10,  color='#d62728', alpha=0.08, zorder=0)
    ax.step(t_rel, d['r_rula'], where='post', color=COLOR_R, label='Right')
    ax.step(t_rel, d['l_rula'], where='post', color=COLOR_L, label='Left', linestyle='--')
    for ts, lbl in d['phase_lines']:
        tr = ts - t0
        ax.axvline(tr, color='k', linestyle=':', linewidth=0.7)
        ax.annotate(lbl, xy=(tr, 9.0), fontsize=FONT_SIZE - 2,
                    rotation=90, ha='left', va='top', color='k')
    ax.set_ylabel('RULA score')
    ax.set_ylim(0.5, 9.5)
    ax.set_yticks([1, 2, 3, 4, 5, 6, 7, 8, 9])
    ax.legend(loc='upper right', framealpha=0.7, fontsize=FONT_SIZE - 2)
    ax.grid(True, axis='y', alpha=0.4)

    ax = axes[1]
    r_ema = ema(d['r_ua'])
    l_ema = ema(d['l_ua'])
    ax.plot(t_rel, d['r_ua'], color=COLOR_R, alpha=ALPHA_RAW, linewidth=0.5)
    ax.plot(t_rel, d['l_ua'], color=COLOR_L, alpha=ALPHA_RAW, linewidth=0.5)
    ax.plot(t_rel, r_ema, color=COLOR_R, label='Right (EMA)')
    ax.plot(t_rel, l_ema, color=COLOR_L, label='Left (EMA)', linestyle='--')
    ax.axhline(20, color='gray', linestyle=':', linewidth=0.7, label='Score-1 (20°)')
    for ts, _ in d['phase_lines']:
        ax.axvline(ts - t0, color='k', linestyle=':', linewidth=0.7)
    ax.set_ylabel('Upper-arm (°)')
    ax.legend(loc='upper right', framealpha=0.7, fontsize=FONT_SIZE - 2)
    ax.grid(True, axis='y', alpha=0.4)

    ax = axes[2]
    r_la_ema = ema(d['r_la'])
    l_la_ema = ema(d['l_la'])
    ax.plot(t_rel, d['r_la'], color=COLOR_R, alpha=ALPHA_RAW, linewidth=0.5)
    ax.plot(t_rel, d['l_la'], color=COLOR_L, alpha=ALPHA_RAW, linewidth=0.5)
    ax.plot(t_rel, r_la_ema, color=COLOR_R, label='Right (EMA)')
    ax.plot(t_rel, l_la_ema, color=COLOR_L, label='Left (EMA)', linestyle='--')
    ax.axhspan(60, 100, color='#2ca02c', alpha=0.10, label='Safe zone [60°,100°]')
    for ts, _ in d['phase_lines']:
        ax.axvline(ts - t0, color='k', linestyle=':', linewidth=0.7)
    ax.set_ylabel('Elbow angle (°)')
    ax.legend(loc='upper right', framealpha=0.7, fontsize=FONT_SIZE - 2)
    ax.grid(True, axis='y', alpha=0.4)

    ax = axes[3]
    valid = ~np.isnan(d['tcp_z'])
    if valid.any():
        ax.step(t_rel[valid], d['tcp_z'][valid], where='post', color='k')
        ax.axhline(0.35, color='gray', linestyle='--', linewidth=0.6, label='Z_min')
        ax.axhline(0.65, color='gray', linestyle=':',  linewidth=0.6, label='Z_max')
        for ts, _ in d['phase_lines']:
            ax.axvline(ts - t0, color='k', linestyle=':', linewidth=0.7)
        ax.legend(loc='upper right', framealpha=0.7, fontsize=FONT_SIZE - 2)
    else:
        ax.text(0.5, 0.5, 'TCP Z — RTDE not available',
                ha='center', va='center', transform=ax.transAxes,
                fontsize=FONT_SIZE - 1, color='gray')
    ax.set_ylabel('TCP Z (m)')
    ax.set_xlabel('Time (s)')
    ax.grid(True, axis='y', alpha=0.4)


def summary_page(trials, pdf):
    """One overlay page: all trials' RULA + upper-arm on shared axes."""
    fig, (ax1, ax2) = plt.subplots(2, 1,
        figsize=(FIG_W_MM * MM_TO_IN, 120 * MM_TO_IN), sharex=False)

    colors = plt.cm.tab10(np.linspace(0, 1, len(trials)))

    ax1.axhspan(0,   2.5, color='#2ca02c', alpha=0.08, zorder=0)
    ax1.axhspan(2.5, 4.5, color='#ffff00', alpha=0.10, zorder=0)
    ax1.axhspan(4.5, 6.5, color='#ff7f0e', alpha=0.10, zorder=0)
    ax1.axhspan(6.5, 10,  color='#d62728', alpha=0.07, zorder=0)

    for i, (d, c) in enumerate(zip(trials, colors)):
        t_rel  = d['t'] - d['t'][0]
        label  = f"T{i+1} {os.path.basename(d['path'])[6:14]}"
        worst  = np.maximum(d['r_rula'], d['l_rula'])
        ax1.step(t_rel, worst, where='post', color=c, label=label, linewidth=0.9)
        worst_ua = np.maximum(d['r_ua'], d['l_ua'])
        ax2.plot(t_rel, ema(worst_ua), color=c, label=label, linewidth=0.9)

    ax1.set_ylabel('RULA score (worst side)')
    ax1.set_ylim(0.5, 9.5)
    ax1.set_yticks([1, 2, 3, 4, 5, 6, 7, 8, 9])
    ax1.set_xlabel('Time (s)')
    ax1.legend(fontsize=FONT_SIZE - 2, ncol=3, loc='upper right', framealpha=0.7)
    ax1.set_title('All trials — RULA score overlay', fontsize=FONT_SIZE)
    ax1.grid(True, axis='y', alpha=0.4)

    ax2.axhline(20, color='gray', linestyle=':', linewidth=0.7, label='Score-1 (20°)')
    ax2.set_ylabel('Upper-arm flexion EMA (°)')
    ax2.set_xlabel('Time (s)')
    ax2.legend(fontsize=FONT_SIZE - 2, ncol=3, loc='upper right', framealpha=0.7)
    ax2.set_title('All trials — upper-arm flexion overlay', fontsize=FONT_SIZE)
    ax2.grid(True, axis='y', alpha=0.4)

    fig.tight_layout(pad=0.5)
    pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', nargs='+', required=True)
    ap.add_argument('--out', default='trial_trajectories.pdf')
    args = ap.parse_args()

    paths = []
    for p in args.csv:
        expanded = sorted(glob.glob(p))
        paths.extend(expanded if expanded else [p])

    trials = []
    for p in paths:
        d = load_trial(p)
        if d is None:
            print(f'WARNING: {p} empty — skipped')
        else:
            trials.append(d)

    if not trials:
        print('ERROR: no valid CSVs.')
        return 1

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    with PdfPages(args.out) as pdf:
        for i, d in enumerate(trials, 1):
            fig, axes = plt.subplots(4, 1,
                figsize=(FIG_W_MM * MM_TO_IN, FIG_H_MM * MM_TO_IN),
                sharex=True)
            title = f'Trial {i} — {os.path.basename(d["path"])}'
            plot_trial(d, fig, axes, title)
            fig.tight_layout(pad=0.4)
            pdf.savefig(fig, bbox_inches='tight')
            plt.close(fig)
            print(f'  Page {i}: {os.path.basename(d["path"])}')

        if len(trials) > 1:
            summary_page(trials, pdf)
            print(f'  Page {len(trials)+1}: summary overlay')

    print(f'Saved: {args.out}  ({len(trials)+1 if len(trials)>1 else 1} pages)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
