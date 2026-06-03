"""
analyze_experiment — Extract metrics (C2/C5/C6/C7/C8/C11) from one or more trial CSVs.

Usage (single trial):
  python3 analyze_experiment.py --csv /tmp/trial_1.csv

Usage (multiple trials — aggregated):
  python3 analyze_experiment.py --csv /tmp/trial_1.csv /tmp/trial_2.csv /tmp/trial_3.csv

  or with a glob:
  python3 analyze_experiment.py --csv /tmp/trial_*.csv

All metrics are derived purely from the recorded data — no paper values are used.
PASS/FAIL is data-driven:
  C5  — code correctness: sub-scores must be consistent with angle values (100%)
  C6  — improvement: RULA score after optimisation must be lower than before
  C8  — physical bound: elbow angle at convergence must be in [60°, 100°]
"""

import argparse
import csv
import glob
import math
import sys

import numpy as np

WARMUP_STABLE_ROWS = 10
MIN_WINDOW         = 10   # minimum rows between before/after windows


# ── CSV loading ───────────────────────────────────────────────────────────────

def load_csv(path):
    with open(path, newline='') as f:
        return list(csv.DictReader(f))


def to_f(v):
    try:    return float(v)
    except: return float('nan')


def to_i(v):
    try:    return int(v)
    except: return -1


# ── Warm-up detection ─────────────────────────────────────────────────────────

def find_warmup_end(r_rula, l_rula):
    run = 0
    for i in range(len(r_rula)):
        if r_rula[i] > 0 or l_rula[i] > 0:
            run += 1
            if run >= WARMUP_STABLE_ROWS:
                return i - WARMUP_STABLE_ROWS + 1
        else:
            run = 0
    return 0


def find_event_rows(rows, keyword):
    return [i for i, r in enumerate(rows) if keyword in r.get('phase_event', '')]


# ── Per-trial metric extraction ───────────────────────────────────────────────

def extract_trial(path):
    """Return a dict of measured scalars for one trial, or None on empty file."""
    rows = load_csv(path)
    if not rows:
        return None

    t       = np.array([to_f(r['timestamp_s'])           for r in rows])
    r_rula  = np.array([to_i(r['right_rula_score'])      for r in rows], dtype=float)
    l_rula  = np.array([to_i(r['left_rula_score'])       for r in rows], dtype=float)
    r_ua    = np.array([to_f(r['right_arm_up'])          for r in rows])
    l_ua    = np.array([to_f(r['left_arm_up'])           for r in rows])
    r_la    = np.array([to_f(r['right_low_angle'])       for r in rows])
    l_la    = np.array([to_f(r['left_low_angle'])        for r in rows])
    r_up_sc = np.array([to_i(r['up_arm_score_right'])    for r in rows])
    l_up_sc = np.array([to_i(r['up_arm_score_left'])     for r in rows])
    r_lo_sc = np.array([to_i(r['lower_arm_score_right']) for r in rows])
    l_lo_sc = np.array([to_i(r['lower_arm_score_left'])  for r in rows])

    worst_rula = np.maximum(r_rula, l_rula)
    worst_ua   = np.maximum(r_ua,   l_ua)
    worst_la   = np.where(np.abs(r_la - 80) > np.abs(l_la - 80), r_la, l_la)

    wu_end = find_warmup_end(r_rula, l_rula)

    opt_idx = [i for i in find_event_rows(rows, 'RULA_OPTIMIZING') if i >= wu_end]
    adj_idx = [i for i in find_event_rows(rows, 'USER_ADJUSTMENT') if i >= wu_end]

    has_phases = (bool(opt_idx) and bool(adj_idx)
                  and adj_idx[0] - opt_idx[0] >= MIN_WINDOW)

    if has_phases:
        i0, i1    = opt_idx[0], adj_idx[0]
        conv_time = t[i1] - t[i0]
        before_sl = slice(i0, min(i0 + 5, i1))
        after_sl  = slice(max(i1 - 20, i0), i1)
        phase_src = 'events'
    else:
        n_anal    = len(rows) - wu_end
        half      = max(1, n_anal // 4)
        i0, i1    = wu_end, len(rows)
        conv_time = float('nan')
        before_sl = slice(wu_end, wu_end + half)
        after_sl  = slice(i1 - half, i1)
        phase_src = 'fallback'

    b_rula = worst_rula[before_sl]
    a_rula = worst_rula[after_sl]
    a_ua   = worst_ua[after_sl]
    a_la   = worst_la[after_sl]

    # C2: best 5 s steady window jitter
    best_jitter = float('nan')
    t_a   = t[wu_end:]
    ua_a  = worst_ua[wu_end:]
    ru_a  = worst_rula[wu_end:]
    for i in range(len(t_a)):
        mask = (t_a >= t_a[i]) & (t_a < t_a[i] + 5.0)
        if mask.sum() < 5:
            continue
        if ru_a[mask].std() < 0.5:
            s = ua_a[mask].std()
            if math.isnan(best_jitter) or s < best_jitter:
                best_jitter = s

    # C5: sub-score consistency
    sl     = slice(wu_end, len(rows))
    ruas   = r_ua[sl];   luas  = l_ua[sl]
    rlas   = r_la[sl];   llas  = l_la[sl]
    rups   = r_up_sc[sl]; lups = l_up_sc[sl]
    rlos   = r_lo_sc[sl]; llos = l_lo_sc[sl]

    ua_tot = (int(np.sum((ruas <= 20) & (rups > 0))) +
              int(np.sum((luas <= 20) & (lups > 0))))
    ua_ok  = (int(np.sum((ruas <= 20) & (rups == 1))) +
              int(np.sum((luas <= 20) & (lups == 1))))
    la_tot = (int(np.sum((rlas > 60) & (rlas < 100) & (rlos > 0))) +
              int(np.sum((llas > 60) & (llas < 100) & (llos > 0))))
    la_ok  = (int(np.sum((rlas > 60) & (rlas < 100) & (rlos == 1))) +
              int(np.sum((llas > 60) & (llas < 100) & (llos == 1))))

    ua_pct = 100 * ua_ok / ua_tot if ua_tot > 0 else float('nan')
    la_pct = 100 * la_ok / la_tot if la_tot > 0 else float('nan')

    return {
        'path':       path,
        'total_rows': len(rows),
        'wu_rows':    wu_end,
        'phase_src':  phase_src,
        'conv_time':  conv_time,
        'rula_before': b_rula.mean() if len(b_rula) else float('nan'),
        'rula_after':  a_rula.mean() if len(a_rula) else float('nan'),
        'ua_mean':    a_ua.mean() if len(a_ua) else float('nan'),
        'ua_std':     a_ua.std()  if len(a_ua) else float('nan'),
        'la_mean':    a_la.mean() if len(a_la) else float('nan'),
        'la_std':     a_la.std()  if len(a_la) else float('nan'),
        'jitter':     best_jitter,
        'ua_pct':     ua_pct,
        'la_pct':     la_pct,
        'ua_tot':     ua_tot,
        'la_tot':     la_tot,
    }


# ── Formatting helpers ────────────────────────────────────────────────────────

def fv(v, unit='', decimals=2):
    if math.isnan(v):
        return 'n/a'
    return f'{v:.{decimals}f}{unit}'


def chk(label, ok, detail=''):
    P = '\033[32mPASS\033[0m'
    F = '\033[31mFAIL\033[0m'
    suffix = f'  ({detail})' if detail else ''
    print(f'  [{ P if ok else F }]  {label}{suffix}')
    return ok


# ── Single-trial report ───────────────────────────────────────────────────────

def print_trial(d, idx=None):
    tag = f'Trial {idx}' if idx is not None else d['path']
    import os
    name = os.path.basename(d['path'])
    print(f"\n  {'─'*66}")
    print(f"  {tag}: {name}")
    print(f"    rows={d['total_rows']}  warm-up={d['wu_rows']} rows"
          f"  phase-src={d['phase_src']}")
    print(f"    C6   RULA  before={fv(d['rula_before'])}  after={fv(d['rula_after'])}")
    print(f"    C7   θ_ua  {fv(d['ua_mean'], '°')} ± {fv(d['ua_std'], '°')}")
    print(f"    C8   θ_la  {fv(d['la_mean'], '°')} ± {fv(d['la_std'], '°')}")
    print(f"    C11  conv  {fv(d['conv_time'], ' s')}")
    print(f"    C2   jitter {fv(d['jitter'], '°')}")
    print(f"    C5   ua {d['ua_ok']}/{d['ua_tot']} ({fv(d['ua_pct'], '%', 0)})  "
          f"la {d['la_ok']}/{d['la_tot']} ({fv(d['la_pct'], '%', 0)})"
          if False else
          f"    C5   ua {d['ua_tot']} rows checked ({fv(d['ua_pct'], '%', 0)})  "
          f"la {d['la_tot']} rows checked ({fv(d['la_pct'], '%', 0)})")


# ── Aggregate across trials ───────────────────────────────────────────────────

def agg(vals):
    """Mean ± std of finite values in list."""
    v = np.array([x for x in vals if not math.isnan(x)])
    if len(v) == 0:
        return float('nan'), float('nan'), 0
    return v.mean(), v.std(), len(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', nargs='+', required=True,
                    help='One or more trial CSV files (globs expanded automatically)')
    args = ap.parse_args()

    # Expand any globs passed as strings (shell may not expand them)
    paths = []
    for p in args.csv:
        expanded = sorted(glob.glob(p))
        paths.extend(expanded if expanded else [p])

    print('=' * 72)
    print(f'Experiment analysis — {len(paths)} trial(s)')
    print('=' * 72)

    trials = []
    for i, path in enumerate(paths, 1):
        d = extract_trial(path)
        if d is None:
            print(f'  WARNING: {path} is empty — skipped')
            continue
        trials.append(d)

    if not trials:
        print('ERROR: no valid trial CSVs loaded.')
        return 1

    # ── Per-trial summary table ───────────────────────────────────────────────
    print(f'\n  {"#":<4} {"file":<30} {"RULA bef":>8} {"RULA aft":>8} '
          f'{"θ_ua°":>8} {"θ_la°":>8} {"conv s":>7} {"jitter°":>8} {"src":<8}')
    print(f'  {"─"*4} {"─"*30} {"─"*8} {"─"*8} {"─"*8} {"─"*8} {"─"*7} {"─"*8} {"─"*8}')
    import os
    for i, d in enumerate(trials, 1):
        name = os.path.basename(d['path'])[:30]
        print(f'  {i:<4} {name:<30} '
              f'{fv(d["rula_before"]):>8} {fv(d["rula_after"]):>8} '
              f'{fv(d["ua_mean"]):>8} {fv(d["la_mean"]):>8} '
              f'{fv(d["conv_time"]):>7} {fv(d["jitter"]):>8} '
              f'{d["phase_src"]:<8}')

    # ── Aggregate ─────────────────────────────────────────────────────────────
    print(f'\n{"=" * 72}')
    print(f'  Aggregate across {len(trials)} trial(s)  (mean ± std)')
    print(f'{"=" * 72}')

    passed = []

    def agg_row(label, vals, unit=''):
        m, s, n = agg(vals)
        print(f'    {label:<38} {fv(m, unit)} ± {fv(s, unit)}  (n={n})')
        return m, s, n

    print()
    rb_m, rb_s, _ = agg_row('C6  RULA before optimisation', [d['rula_before'] for d in trials])
    ra_m, ra_s, _ = agg_row('C6  RULA after  optimisation', [d['rula_after']  for d in trials])
    ok_c6 = (not math.isnan(rb_m) and not math.isnan(ra_m) and ra_m < rb_m)
    passed.append(chk('C6   RULA score decreased', ok_c6,
                      f'{rb_m:.2f} → {ra_m:.2f}'))

    print()
    ua_m, ua_s, _ = agg_row('C7  θ_ua at convergence (°)',  [d['ua_mean']    for d in trials], '°')
    print()
    la_m, la_s, _ = agg_row('C8  θ_la at convergence (°)',  [d['la_mean']    for d in trials], '°')
    ok_c8 = not math.isnan(la_m) and 60 <= la_m <= 100
    passed.append(chk('C8   θ_la in ergonomic safe zone [60°, 100°]',
                      ok_c8, f'{la_m:.1f}°'))

    print()
    ct_m, ct_s, ct_n = agg_row('C11 Convergence time (s)',     [d['conv_time']  for d in trials], ' s')
    if math.isnan(ct_m):
        print('         (no phase events recorded — cannot compute convergence time)')

    print()
    jt_m, jt_s, _ = agg_row('C2  Jitter std (°)',             [d['jitter']     for d in trials], '°')

    print()
    # C5: pool all rows across trials
    ua_tot_all = sum(d['ua_tot'] for d in trials)
    la_tot_all = sum(d['la_tot'] for d in trials)
    ua_pcts = [d['ua_pct'] for d in trials if not math.isnan(d['ua_pct'])]
    la_pcts = [d['la_pct'] for d in trials if not math.isnan(d['la_pct'])]
    ua_pool_pct = np.mean(ua_pcts) if ua_pcts else float('nan')
    la_pool_pct = np.mean(la_pcts) if la_pcts else float('nan')
    print(f'    {"C5  θ_ua≤20° → up_score=1":<38} {fv(ua_pool_pct, "%", 1)}  '
          f'({ua_tot_all} total rows)')
    print(f'    {"C5  θ_la∈(60°,100°) → lo_score=1":<38} {fv(la_pool_pct, "%", 1)}  '
          f'({la_tot_all} total rows)')
    ok_ua = ua_tot_all == 0 or ua_pool_pct == 100
    ok_la = la_tot_all == 0 or la_pool_pct == 100
    passed.append(chk('C5   upper-arm sub-score consistent',
                      ok_ua, 'no θ_ua≤20° rows' if ua_tot_all == 0 else f'{ua_pool_pct:.1f}%'))
    passed.append(chk('C5   lower-arm sub-score consistent',
                      ok_la, 'no safe-zone rows' if la_tot_all == 0 else f'{la_pool_pct:.1f}%'))

    print('\n' + '=' * 72)
    print(f'  {sum(passed)}/{len(passed)} checks passed')
    print('=' * 72)
    return 0 if all(passed) else 1


if __name__ == '__main__':
    sys.exit(main())
