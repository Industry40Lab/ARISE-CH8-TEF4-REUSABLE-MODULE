"""
generate_report — Full scientific report PDF for all trial CSVs.

Produces a multi-page PDF:
  Page 1  : Cover — aggregate results table + bar charts
  Page 2–N: One page per trial (4-subplot trajectory)
  Page N+1: Summary overlay (all trials, RULA + upper-arm)
  Page N+2: Paper-ready standalone figures (RULA overlay, upper-arm overlay)

Usage:
  python3 generate_report.py --csv /path/to/trial_*.csv --out report.pdf
"""

import argparse
import csv
import glob
import math
import os
import sys
from collections import deque

import numpy as np

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.lines import Line2D
    import matplotlib.patches as mpatches
except ImportError:
    print('ERROR: pip install matplotlib')
    sys.exit(1)

# ── Style ─────────────────────────────────────────────────────────────────────
FS   = 9
FW   = 170 * (1/25.4)   # full page width (mm→in)
FH   = 220 * (1/25.4)
FW_S = 88  * (1/25.4)   # single-column paper figure

plt.rcParams.update({
    'font.family':      'DejaVu Serif',
    'font.size':        FS,
    'axes.labelsize':   FS,
    'xtick.labelsize':  FS - 1,
    'ytick.labelsize':  FS - 1,
    'legend.fontsize':  FS - 1,
    'lines.linewidth':  1.0,
    'axes.linewidth':   0.6,
    'grid.linewidth':   0.3,
    'grid.alpha':       0.4,
    'pdf.fonttype':     42,
    'ps.fonttype':      42,
})

CR = '#d62728'
CL = '#1f77b4'
TRIAL_COLORS = plt.cm.tab10(np.linspace(0, 0.9, 10))

EMA_A = 0.10
WARMUP_STABLE = 10
MIN_WIN = 10


# ── Data helpers ──────────────────────────────────────────────────────────────

def to_f(v):
    try:    return float(v)
    except: return float('nan')

def to_i(v):
    try:    return int(v)
    except: return -1

def ema(arr, a=EMA_A):
    out = np.empty_like(arr, dtype=float)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = a * arr[i] + (1 - a) * out[i-1]
    return out

def find_warmup_end(r_rula, l_rula):
    run = 0
    for i in range(len(r_rula)):
        if r_rula[i] > 0 or l_rula[i] > 0:
            run += 1
            if run >= WARMUP_STABLE:
                return i - WARMUP_STABLE + 1
        else:
            run = 0
    return 0

def event_rows(rows, kw):
    return [(i, to_f(r['timestamp_s'])) for i, r in enumerate(rows)
            if kw in r.get('phase_event', '')]

def fv(v, decimals=2, unit=''):
    return 'n/a' if math.isnan(v) else f'{v:.{decimals}f}{unit}'


# ── Load one trial ────────────────────────────────────────────────────────────

def load_trial(path):
    with open(path, newline='') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None

    t      = np.array([to_f(r['timestamp_s'])           for r in rows])
    r_rula = np.array([to_i(r['right_rula_score'])      for r in rows], dtype=float)
    l_rula = np.array([to_i(r['left_rula_score'])       for r in rows], dtype=float)
    r_ua   = np.array([to_f(r['right_arm_up'])          for r in rows])
    l_ua   = np.array([to_f(r['left_arm_up'])           for r in rows])
    r_la   = np.array([to_f(r['right_low_angle'])       for r in rows])
    l_la   = np.array([to_f(r['left_low_angle'])        for r in rows])
    r_ups  = np.array([to_i(r['up_arm_score_right'])    for r in rows])
    l_ups  = np.array([to_i(r['up_arm_score_left'])     for r in rows])
    r_los  = np.array([to_i(r['lower_arm_score_right']) for r in rows])
    l_los  = np.array([to_i(r['lower_arm_score_left'])  for r in rows])
    tcp_z  = np.array([to_f(r['tcp_z_m'])               for r in rows])

    worst_rula = np.maximum(r_rula, l_rula)
    worst_ua   = np.maximum(r_ua, l_ua)
    worst_la   = np.where(np.abs(r_la - 80) > np.abs(l_la - 80), r_la, l_la)

    wu = find_warmup_end(r_rula, l_rula)
    opt_ev = [(i, ts) for i, ts in event_rows(rows, 'RULA_OPTIMIZING') if i >= wu]
    adj_ev = [(i, ts) for i, ts in event_rows(rows, 'USER_ADJUSTMENT')  if i >= wu]
    has_ph = bool(opt_ev) and bool(adj_ev) and adj_ev[0][0] - opt_ev[0][0] >= MIN_WIN

    if has_ph:
        i0, i1    = opt_ev[0][0], adj_ev[0][0]
        conv_time = t[i1] - t[i0]
        before_sl = slice(i0, min(i0 + 5, i1))
        after_sl  = slice(max(i1 - 20, i0), i1)
        src = 'events'
    else:
        n = len(rows) - wu
        h = max(1, n // 4)
        i0, i1    = wu, len(rows)
        conv_time = float('nan')
        before_sl = slice(wu, wu + h)
        after_sl  = slice(i1 - h, i1)
        src = 'fallback'

    phase_lines = ([(ts, 'OPT')  for _, ts in opt_ev] +
                   [(ts, 'Conv') for _, ts in adj_ev])

    # jitter
    best_j = float('nan')
    ta, ua_a, ru_a = t[wu:], worst_ua[wu:], worst_rula[wu:]
    for i in range(len(ta)):
        mask = (ta >= ta[i]) & (ta < ta[i] + 5.0)
        if mask.sum() < 5 or ru_a[mask].std() >= 0.5:
            continue
        s = ua_a[mask].std()
        if math.isnan(best_j) or s < best_j:
            best_j = s

    return dict(
        path=path, rows=rows,
        t=t, r_rula=r_rula, l_rula=l_rula,
        r_ua=r_ua, l_ua=l_ua, r_la=r_la, l_la=l_la,
        r_ups=r_ups, l_ups=l_ups, r_los=r_los, l_los=l_los,
        tcp_z=tcp_z,
        worst_rula=worst_rula, worst_ua=worst_ua, worst_la=worst_la,
        wu=wu, phase_lines=phase_lines, src=src,
        conv_time=conv_time,
        rula_before=worst_rula[before_sl].mean() if len(worst_rula[before_sl]) else float('nan'),
        rula_after =worst_rula[after_sl].mean()  if len(worst_rula[after_sl])  else float('nan'),
        ua_mean=worst_ua[after_sl].mean() if len(worst_ua[after_sl]) else float('nan'),
        ua_std =worst_ua[after_sl].std()  if len(worst_ua[after_sl]) else float('nan'),
        la_mean=worst_la[after_sl].mean() if len(worst_la[after_sl]) else float('nan'),
        la_std =worst_la[after_sl].std()  if len(worst_la[after_sl]) else float('nan'),
        jitter=best_j,
    )


# ── Page 1: Cover ─────────────────────────────────────────────────────────────

def page_cover(trials, pdf):
    fig = plt.figure(figsize=(FW, FH))
    gs  = gridspec.GridSpec(3, 2, figure=fig, hspace=0.55, wspace=0.35,
                            top=0.92, bottom=0.08, left=0.10, right=0.95)

    # ── Title ──────────────────────────────────────────────────────────────
    fig.text(0.5, 0.96,
             'Ergonomic Posture Optimisation — Experimental Results',
             ha='center', va='top', fontsize=12, fontweight='bold')
    fig.text(0.5, 0.935,
             f'{len(trials)} trials recorded  |  RULA-based gradient-descent optimiser  |  UR5e + RealSense D435i',
             ha='center', va='top', fontsize=FS - 1, color='gray')

    # ── Results table ──────────────────────────────────────────────────────
    ax_tbl = fig.add_subplot(gs[0, :])
    ax_tbl.axis('off')

    names   = [os.path.basename(d['path'])[6:20] for d in trials]
    rb      = [fv(d['rula_before'], 1) for d in trials]
    ra      = [fv(d['rula_after'],  1) for d in trials]
    ua      = [f"{fv(d['ua_mean'],1)}±{fv(d['ua_std'],1)}" for d in trials]
    la      = [f"{fv(d['la_mean'],1)}±{fv(d['la_std'],1)}" for d in trials]
    ct      = [fv(d['conv_time'], 1, ' s') for d in trials]
    jt      = [fv(d['jitter'], 2, '°') for d in trials]
    src     = [d['src'] for d in trials]

    # aggregate row
    def agg_col(vals):
        v = [float(x) for x in vals if x != 'n/a' and '±' not in x]
        if not v: return 'n/a'
        return f'{np.mean(v):.1f}±{np.std(v):.1f}'

    rb_vals  = [d['rula_before'] for d in trials]
    ra_vals  = [d['rula_after']  for d in trials]
    ua_vals  = [d['ua_mean'] for d in trials]
    la_vals  = [d['la_mean'] for d in trials]
    ct_vals  = [d['conv_time'] for d in trials]
    jt_vals  = [d['jitter'] for d in trials]

    def agg(vals):
        v = np.array([x for x in vals if not math.isnan(x)])
        return (f'{v.mean():.1f}±{v.std():.1f}', len(v)) if len(v) else ('n/a', 0)

    rb_a, _  = agg(rb_vals)
    ra_a, _  = agg(ra_vals)
    ua_a, _  = agg(ua_vals)
    la_a, _  = agg(la_vals)
    ct_a, cn = agg(ct_vals)
    jt_a, _  = agg(jt_vals)

    col_labels = ['Trial', 'RULA before', 'RULA after', 'θ_ua (°)', 'θ_la (°)',
                  'Conv. time', 'Jitter', 'Source']
    rows_data  = list(zip([f'T{i+1}' for i in range(len(trials))],
                          rb, ra, ua, la, ct, jt, src))
    rows_data.append(('Mean±SD', rb_a, ra_a, ua_a, la_a,
                      ct_a + f' (n={cn})', jt_a, ''))

    tbl = ax_tbl.table(
        cellText=rows_data,
        colLabels=col_labels,
        loc='center', cellLoc='center')
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(FS - 1)
    tbl.scale(1, 1.4)

    # highlight header and aggregate row
    for j in range(len(col_labels)):
        tbl[(0, j)].set_facecolor('#2c3e50')
        tbl[(0, j)].set_text_props(color='white', fontweight='bold')
        tbl[(len(rows_data), j)].set_facecolor('#d5e8d4')
        tbl[(len(rows_data), j)].set_text_props(fontweight='bold')

    ax_tbl.set_title('Per-trial metrics (warm-up stripped; fallback = no phase events)',
                     fontsize=FS - 1, pad=8, loc='left', color='gray')

    # ── Bar: RULA before/after ─────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[1, 0])
    x   = np.arange(len(trials))
    w   = 0.35
    bars_b = ax1.bar(x - w/2, rb_vals, w, label='Before', color='#c0392b', alpha=0.8)
    bars_a = ax1.bar(x + w/2, ra_vals, w, label='After',  color='#27ae60', alpha=0.8)
    ax1.set_xticks(x)
    ax1.set_xticklabels([f'T{i+1}' for i in range(len(trials))])
    ax1.set_ylabel('RULA grand score')
    ax1.set_title('C6 — RULA score before vs after')
    ax1.set_ylim(0, 9)
    ax1.axhline(np.nanmean(rb_vals), color='#c0392b', linestyle='--', linewidth=0.7, alpha=0.6)
    ax1.axhline(np.nanmean(ra_vals), color='#27ae60', linestyle='--', linewidth=0.7, alpha=0.6)
    ax1.legend(fontsize=FS - 2)
    ax1.grid(True, axis='y')

    # ── Bar: convergence time ──────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[1, 1])
    ct_finite = [(i, d['conv_time']) for i, d in enumerate(trials)
                 if not math.isnan(d['conv_time'])]
    if ct_finite:
        xi, yi = zip(*ct_finite)
        ax2.bar([f'T{i+1}' for i in xi], yi, color='#2980b9', alpha=0.8)
        ax2.axhline(np.mean(yi), color='k', linestyle='--', linewidth=0.7,
                    label=f'Mean={np.mean(yi):.1f} s')
        ax2.legend(fontsize=FS - 2)
    ax2.set_ylabel('Convergence time (s)')
    ax2.set_title('C11 — Convergence time per trial')
    ax2.grid(True, axis='y')

    # ── Box: θ_ua and θ_la distributions ──────────────────────────────────
    ax3 = fig.add_subplot(gs[2, 0])
    ua_data = [d['worst_ua'][d['wu']:] for d in trials]
    bp = ax3.boxplot(ua_data, patch_artist=True, medianprops=dict(color='k', linewidth=1.2))
    for patch, c in zip(bp['boxes'], TRIAL_COLORS):
        patch.set_facecolor((*c[:3], 0.6))
    ax3.axhline(20, color='gray', linestyle=':', linewidth=0.7, label='Score-1 (20°)')
    ax3.set_xticklabels([f'T{i+1}' for i in range(len(trials))])
    ax3.set_ylabel('Upper-arm flexion (°)')
    ax3.set_title('C7 — θ_ua distribution per trial')
    ax3.legend(fontsize=FS - 2)
    ax3.grid(True, axis='y')

    ax4 = fig.add_subplot(gs[2, 1])
    la_data = [d['worst_la'][d['wu']:] for d in trials]
    bp2 = ax4.boxplot(la_data, patch_artist=True, medianprops=dict(color='k', linewidth=1.2))
    for patch, c in zip(bp2['boxes'], TRIAL_COLORS):
        patch.set_facecolor((*c[:3], 0.6))
    ax4.axhspan(60, 100, color='#27ae60', alpha=0.10, label='Safe zone [60°,100°]')
    ax4.set_xticklabels([f'T{i+1}' for i in range(len(trials))])
    ax4.set_ylabel('Elbow angle (°)')
    ax4.set_title('C8 — θ_la distribution per trial')
    ax4.legend(fontsize=FS - 2)
    ax4.grid(True, axis='y')

    pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)


# ── Per-trial page ────────────────────────────────────────────────────────────

def page_trial(d, idx, pdf):
    fig, axes = plt.subplots(4, 1, figsize=(FW, FH), sharex=True)
    t0    = d['t'][0]
    t_rel = d['t'] - t0
    name  = os.path.basename(d['path'])

    fig.suptitle(f'Trial {idx} — {name}   '
                 f'(rows={len(d["t"])}, warm-up={d["wu"]} rows, src={d["src"]})',
                 fontsize=FS, fontweight='bold', y=0.98)

    # RULA
    ax = axes[0]
    ax.axhspan(0,   2.5, color='#27ae60', alpha=0.09, zorder=0)
    ax.axhspan(2.5, 4.5, color='#f1c40f', alpha=0.11, zorder=0)
    ax.axhspan(4.5, 6.5, color='#e67e22', alpha=0.11, zorder=0)
    ax.axhspan(6.5, 10,  color='#c0392b', alpha=0.08, zorder=0)
    ax.step(t_rel, d['r_rula'], where='post', color=CR, label='Right')
    ax.step(t_rel, d['l_rula'], where='post', color=CL, label='Left', linestyle='--')
    for ts, lbl in d['phase_lines']:
        tr = ts - t0
        ax.axvline(tr, color='k', linestyle=':', linewidth=0.8)
        ax.annotate(lbl, xy=(tr, 9.1), fontsize=FS-2, rotation=90,
                    ha='left', va='top', color='k')
    ax.set_ylabel('RULA score')
    ax.set_ylim(0.5, 9.5)
    ax.set_yticks(range(1, 10))
    ax.legend(loc='upper right', fontsize=FS-2, framealpha=0.7)
    ax.grid(True, axis='y')

    # Upper-arm
    ax = axes[1]
    ax.plot(t_rel, d['r_ua'], color=CR, alpha=0.18, linewidth=0.6)
    ax.plot(t_rel, d['l_ua'], color=CL, alpha=0.18, linewidth=0.6)
    ax.plot(t_rel, ema(d['r_ua']), color=CR, label='Right (EMA)')
    ax.plot(t_rel, ema(d['l_ua']), color=CL, label='Left (EMA)', linestyle='--')
    ax.axhline(20, color='gray', linestyle=':', linewidth=0.8, label='Score-1 (20°)')
    for ts, _ in d['phase_lines']:
        ax.axvline(ts - t0, color='k', linestyle=':', linewidth=0.8)
    ax.set_ylabel('Upper-arm (°)')
    ax.legend(loc='upper right', fontsize=FS-2, framealpha=0.7)
    ax.grid(True, axis='y')

    # Elbow
    ax = axes[2]
    ax.plot(t_rel, d['r_la'], color=CR, alpha=0.18, linewidth=0.6)
    ax.plot(t_rel, d['l_la'], color=CL, alpha=0.18, linewidth=0.6)
    ax.plot(t_rel, ema(d['r_la']), color=CR, label='Right (EMA)')
    ax.plot(t_rel, ema(d['l_la']), color=CL, label='Left (EMA)', linestyle='--')
    ax.axhspan(60, 100, color='#27ae60', alpha=0.10, label='Safe zone [60°,100°]')
    for ts, _ in d['phase_lines']:
        ax.axvline(ts - t0, color='k', linestyle=':', linewidth=0.8)
    ax.set_ylabel('Elbow angle (°)')
    ax.legend(loc='upper right', fontsize=FS-2, framealpha=0.7)
    ax.grid(True, axis='y')

    # TCP Z
    ax = axes[3]
    valid = ~np.isnan(d['tcp_z'])
    if valid.any():
        ax.step(t_rel[valid], d['tcp_z'][valid], where='post', color='k')
        ax.axhline(0.35, color='gray', linestyle='--', linewidth=0.7, label='Z_min=0.35 m')
        ax.axhline(0.65, color='gray', linestyle=':',  linewidth=0.7, label='Z_max=0.65 m')
        for ts, _ in d['phase_lines']:
            ax.axvline(ts - t0, color='k', linestyle=':', linewidth=0.8)
        ax.legend(loc='upper right', fontsize=FS-2, framealpha=0.7)
    else:
        ax.text(0.5, 0.5, 'TCP Z not available', ha='center', va='center',
                transform=ax.transAxes, color='gray', fontsize=FS-1)
    ax.set_ylabel('TCP Z (m)')
    ax.set_xlabel('Time from warm-up end (s)')
    ax.grid(True, axis='y')

    # Metric annotation
    ann = (f'RULA: {fv(d["rula_before"],1)} → {fv(d["rula_after"],1)}   '
           f'θ_ua={fv(d["ua_mean"],1)}°±{fv(d["ua_std"],1)}°   '
           f'θ_la={fv(d["la_mean"],1)}°±{fv(d["la_std"],1)}°   '
           f'conv={fv(d["conv_time"],1," s")}   '
           f'jitter={fv(d["jitter"],2,"°")}')
    fig.text(0.5, 0.005, ann, ha='center', fontsize=FS-2, color='#333333',
             bbox=dict(boxstyle='round,pad=0.3', facecolor='#f0f0f0', edgecolor='none'))

    fig.tight_layout(rect=[0, 0.025, 1, 0.975], h_pad=0.4)
    pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)


# ── Summary overlay page ──────────────────────────────────────────────────────

def page_summary(trials, pdf):
    fig, axes = plt.subplots(3, 1, figsize=(FW, FH * 0.75), sharex=False)

    fig.suptitle('All Trials — Overlay Summary', fontsize=11, fontweight='bold', y=0.98)

    for i, d in enumerate(trials):
        c     = TRIAL_COLORS[i]
        t_rel = d['t'] - d['t'][0]
        lbl   = f'T{i+1}'

        # RULA
        worst = np.maximum(d['r_rula'], d['l_rula'])
        axes[0].step(t_rel, worst, where='post', color=c, label=lbl, linewidth=0.9)

        # Upper-arm EMA
        axes[1].plot(t_rel, ema(np.maximum(d['r_ua'], d['l_ua'])),
                     color=c, label=lbl, linewidth=0.9)

        # Elbow EMA
        axes[2].plot(t_rel, ema(np.where(
            np.abs(d['r_la'] - 80) > np.abs(d['l_la'] - 80), d['r_la'], d['l_la'])),
            color=c, label=lbl, linewidth=0.9)

    axes[0].axhspan(4.5, 6.5, color='#e67e22', alpha=0.08, zorder=0)
    axes[0].axhspan(2.5, 4.5, color='#f1c40f', alpha=0.08, zorder=0)
    axes[0].set_ylabel('RULA score (worst side)')
    axes[0].set_ylim(0.5, 9.5)
    axes[0].set_yticks(range(1, 10))
    axes[0].legend(fontsize=FS-2, ncol=len(trials), loc='upper right', framealpha=0.7)
    axes[0].grid(True, axis='y')

    axes[1].axhline(20, color='gray', linestyle=':', linewidth=0.8, label='Score-1 (20°)')
    axes[1].set_ylabel('Upper-arm EMA (°)')
    axes[1].legend(fontsize=FS-2, ncol=len(trials)+1, loc='upper right', framealpha=0.7)
    axes[1].grid(True, axis='y')

    axes[2].axhspan(60, 100, color='#27ae60', alpha=0.10, label='Safe zone [60°,100°]')
    axes[2].set_ylabel('Elbow EMA (°)')
    axes[2].set_xlabel('Time from start (s)')
    axes[2].legend(fontsize=FS-2, ncol=len(trials)+1, loc='upper right', framealpha=0.7)
    axes[2].grid(True, axis='y')

    fig.tight_layout(rect=[0, 0, 1, 0.97], h_pad=0.5)
    pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)


# ── Paper-ready figures (single-column, 88 mm) ───────────────────────────────

def page_paper_figures(trials, pdf):
    """Two compact figures side-by-side on one landscape page, IEEE style."""
    fig, axes = plt.subplots(1, 2, figsize=(FW, 90*(1/25.4)))
    fig.suptitle('Paper-ready figures (88 mm single-column each)',
                 fontsize=FS-1, color='gray', y=1.01)

    # Fig A: RULA overlay
    ax = axes[0]
    ax.axhspan(2.5, 4.5, color='#f1c40f', alpha=0.10, zorder=0)
    ax.axhspan(4.5, 6.5, color='#e67e22', alpha=0.10, zorder=0)
    for i, d in enumerate(trials):
        c     = TRIAL_COLORS[i]
        t_rel = d['t'] - d['t'][0]
        worst = np.maximum(d['r_rula'], d['l_rula'])
        ax.step(t_rel, worst, where='post', color=c,
                label=f'T{i+1}', linewidth=0.8, alpha=0.85)
    ax.set_ylabel('RULA score')
    ax.set_xlabel('Time (s)')
    ax.set_ylim(0.5, 9.5)
    ax.set_yticks(range(1, 10))
    ax.legend(fontsize=FS-3, ncol=2, framealpha=0.7)
    ax.set_title('(a) RULA grand score', fontsize=FS-1)
    ax.grid(True, axis='y')

    # Fig B: upper-arm EMA overlay
    ax = axes[1]
    for i, d in enumerate(trials):
        c     = TRIAL_COLORS[i]
        t_rel = d['t'] - d['t'][0]
        ax.plot(t_rel, ema(np.maximum(d['r_ua'], d['l_ua'])),
                color=c, label=f'T{i+1}', linewidth=0.8, alpha=0.85)
    ax.axhline(20, color='k', linestyle=':', linewidth=0.7, label='Score-1 (20°)')
    ax.set_ylabel('Upper-arm flexion (°)')
    ax.set_xlabel('Time (s)')
    ax.legend(fontsize=FS-3, ncol=2, framealpha=0.7)
    ax.set_title('(b) Upper-arm flexion (EMA)', fontsize=FS-1)
    ax.grid(True, axis='y')

    fig.tight_layout()
    pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', nargs='+', required=True)
    ap.add_argument('--out', default='experiment_report.pdf')
    args = ap.parse_args()

    paths = []
    for p in args.csv:
        ex = sorted(glob.glob(p))
        paths.extend(ex if ex else [p])

    print(f'Loading {len(paths)} CSV files...')
    trials = []
    for p in paths:
        d = load_trial(p)
        if d is None:
            print(f'  SKIP (empty): {p}')
        else:
            trials.append(d)
            print(f'  OK  {os.path.basename(p)}  rows={len(d["t"])}  wu={d["wu"]}  src={d["src"]}')

    if not trials:
        print('ERROR: no valid trials.')
        return 1

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    with PdfPages(args.out) as pdf:
        info = pdf.infodict()
        info['Title']   = 'Ergonomic Posture Optimisation — Experimental Report'
        info['Subject'] = 'RULA-based gradient-descent optimiser, UR5e, RealSense D435i'

        print('Generating cover page...')
        page_cover(trials, pdf)

        for i, d in enumerate(trials, 1):
            print(f'Generating trial {i} page...')
            page_trial(d, i, pdf)

        print('Generating summary overlay page...')
        page_summary(trials, pdf)

        print('Generating paper-ready figures page...')
        page_paper_figures(trials, pdf)

    n_pages = 1 + len(trials) + 2
    print(f'\nSaved: {args.out}  ({n_pages} pages)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
