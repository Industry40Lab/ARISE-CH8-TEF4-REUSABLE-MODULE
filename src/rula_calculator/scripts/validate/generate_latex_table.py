"""
generate_latex_table — Print a ready-to-paste LaTeX results table.

Reads measured values from a trial CSV and substitutes them into the paper's
Table IV (§4.3).  Missing values fall back to paper-reported values with a
footnote marker (*).

Usage:
  python3 generate_latex_table.py --csv /tmp/trial.csv
  python3 generate_latex_table.py          # prints paper values only (all *)
"""

import argparse
import csv
import math
import sys

import numpy as np


def to_f(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return float('nan')


def to_i(v):
    try:
        return int(v)
    except (ValueError, TypeError):
        return -1


def load_csv(path):
    rows = []
    with open(path, newline='') as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def find_event_rows(rows, keyword):
    return [i for i, r in enumerate(rows) if keyword in r.get('phase_event', '')]


def fmt(val, std=None, paper=None, unit=''):
    """Return a LaTeX-safe string; append * if falling back to paper value."""
    if math.isnan(val):
        return f'{paper}\\textsuperscript{{*}}'
    if std is not None and not math.isnan(std):
        return f'${val:.1f}\\pm{std:.1f}${unit}'
    return f'${val:.1f}${unit}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', default=None, help='Path to trial CSV (optional)')
    args = ap.parse_args()

    # Defaults (paper-reported)
    rula_before = rula_after = float('nan')
    ua_before_m = ua_before_s = float('nan')
    ua_after_m  = ua_after_s  = float('nan')
    la_after_m  = la_after_s  = float('nan')
    conv_time   = float('nan')
    move_min = move_max  = float('nan')
    step_mean   = float('nan')

    if args.csv:
        rows = load_csv(args.csv)
        t      = np.array([to_f(r['timestamp_s'])        for r in rows])
        r_rula = np.array([to_i(r['right_rula_score'])   for r in rows], dtype=float)
        l_rula = np.array([to_i(r['left_rula_score'])    for r in rows], dtype=float)
        r_ua   = np.array([to_f(r['right_arm_up'])       for r in rows])
        l_ua   = np.array([to_f(r['left_arm_up'])        for r in rows])
        r_la   = np.array([to_f(r['right_low_angle'])    for r in rows])
        l_la   = np.array([to_f(r['left_low_angle'])     for r in rows])
        tcp_z  = np.array([to_f(r['tcp_z_m'])            for r in rows])

        worst_rula = np.maximum(r_rula, l_rula)
        worst_ua   = np.maximum(r_ua, l_ua)
        worst_la   = np.where(
            np.abs(r_la - 80) > np.abs(l_la - 80), r_la, l_la)

        opt_idx = find_event_rows(rows, 'RULA_OPTIMIZING')
        adj_idx = find_event_rows(rows, 'USER_ADJUSTMENT')

        if opt_idx:
            i0 = opt_idx[0]
            ua_before_m = worst_ua[:i0 + 5].mean()
            ua_before_s = worst_ua[:i0 + 5].std()
            rula_before = worst_rula[:i0 + 5].mean()

        if opt_idx and adj_idx:
            i0, i1 = opt_idx[0], adj_idx[0]
            rula_after = worst_rula[max(i1 - 5, i0):i1].mean()
            ua_after_m = worst_ua[max(i1 - 20, i0):i1].mean()
            ua_after_s = worst_ua[max(i1 - 20, i0):i1].std()
            la_after_m = worst_la[max(i1 - 20, i0):i1].mean()
            la_after_s = worst_la[max(i1 - 20, i0):i1].std()
            conv_time  = t[i1] - t[i0]

            # Count robot moves from TCP Z changes
            z_valid = tcp_z[~np.isnan(tcp_z)]
            if len(z_valid) > 1:
                dz      = np.abs(np.diff(z_valid))
                moves   = dz[dz > 0.001]   # threshold: 1 mm
                if len(moves) > 0:
                    move_min  = len(moves)
                    move_max  = len(moves)   # single trial → no range
                    step_mean = moves.mean() * 1000   # → mm

    lines = [
        r'\begin{table}[htbp]',
        r'\caption{Experimental results.}',
        r'\label{tab:results}',
        r'\centering',
        r'\begin{tabular}{lcc}',
        r'\toprule',
        r'Metric & Before optimisation & After optimisation \\',
        r'\midrule',
    ]

    def row(label, before, after):
        return f'{label} & {before} & {after} \\\\'

    rula_b_str = fmt(rula_before, paper='6--7')
    rula_a_str = fmt(rula_after,  paper='3--4')
    ua_b_str   = fmt(ua_before_m, ua_before_s, paper='$47.3\\pm4.1$', unit='°')
    ua_a_str   = fmt(ua_after_m,  ua_after_s,  paper='$21.8\\pm3.2$', unit='°')
    la_a_str   = fmt(la_after_m,  la_after_s,  paper='$74.6\\pm5.4$', unit='°')
    ct_str     = fmt(conv_time, paper='32.8', unit=' s')

    if not math.isnan(move_min):
        mv_str = f'${move_min:.0f}$--${move_max:.0f}$' if move_min != move_max \
                 else f'${move_min:.0f}$'
    else:
        mv_str = '18--27\\textsuperscript{*}'

    st_str = fmt(step_mean, paper='6.3', unit=' mm')

    lines += [
        row('RULA grand score',        rula_b_str, rula_a_str),
        row('Upper-arm flexion (°)',    ua_b_str,   ua_a_str),
        row('Elbow angle (°)',          '---',      la_a_str),
        row('Convergence time',         '---',      ct_str),
        row('Move count',               '---',      mv_str),
        row('Mean step size',           '---',      st_str),
        r'\bottomrule',
        r'\end{tabular}',
    ]

    if any(math.isnan(v) for v in [rula_before, rula_after, ua_before_m,
                                    ua_after_m, la_after_m, conv_time, step_mean]):
        lines.append(
            r'\begin{tablenotes}\small'
            r'\item[*] Paper-reported value (no CSV data available).'
            r'\end{tablenotes}')

    lines.append(r'\end{table}')

    print('\n'.join(lines))
    return 0


if __name__ == '__main__':
    sys.exit(main())
