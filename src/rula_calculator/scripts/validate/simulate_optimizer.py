"""
C6, C7, C8, C11 — Optimizer convergence simulation (v2, literature-calibrated).

Claims (paper §4.3):
  C6  RULA grand score reduces from 6–7 to 3–4 within 28–45 s.
  C7  Upper-arm flexion converges into the RULA score-1 band (≤20°).
  C8  Elbow angle converges inside [60°, 100°].
  C11 Mean convergence time ≈ 32.8 s.

Kinematic improvements over v1 (all parameters cited in monte_carlo_citation.md):
  • Per-trial anthropometric variability in Jacobians and reference angles
    (Pheasant & Haslegrave 2006; PEROSH 2018; Chaffin et al. 2006).
  • AR(1) postural sway (ρ = 0.78, f₀ = 0.40 Hz) replacing i.i.d. noise
    (Mochizuki et al. 2006; Carpenter et al. 2010).
  • Poisson reach-perturbation events (mean 10 s interval, spike 4–12°,
    decay τ = 2 s) from Drury & Wick (1984) and Rempel et al. (2006).
  • Bilateral arm model: dominant (right) arm held 5.2 ± 3.1° higher;
    non-dominant (left) sway 30 % larger
    (Kee & Karwowski 2001; Sadeghi et al. / PMC6908899 2019).

No ROS runtime required.
"""

import sys
import math
import collections
import numpy as np

# ── Nominal kinematic constants ───────────────────────────────────────────────
Z_REF  = 0.60    # m  — representative initial Z (arm elevated)
UA_REF = 47.3    # °  — upper-arm flexion at Z_REF (nominal, both arms)
LA_REF = 55.0    # °  — elbow angle at Z_REF (slightly below safe zone)
J_UA   =  184.0  # d(θ_ua)/dZ  [°/m]   raising PCB raises arm
J_LA   = -140.0  # d(θ_la)/dZ  [°/m]   raising PCB closes elbow

Z_MIN = 0.30     # m — extended workspace for short operators (PEROSH 2018 §2.3)
Z_MAX = 0.65     # m


def arm_angles(Z, ua_ref=UA_REF, la_ref=LA_REF, j_ua=J_UA, j_la=J_LA):
    """Return (upper_arm_angle, elbow_angle) at height Z for given kinematics."""
    ua = max(0.0, ua_ref + j_ua * (Z - Z_REF))
    la = max(10.0, min(170.0, la_ref + j_la * (Z - Z_REF)))
    return ua, la


# ── RULA tables (verbatim from rula_calculator.py) ───────────────────────────

tableA_in = np.array([
    [1, 2, 2, 2, 2, 3, 3, 3], [2, 2, 2, 2, 3, 3, 3, 3], [2, 3, 3, 3, 3, 3, 4, 4],
    [2, 3, 3, 3, 3, 4, 4, 4], [3, 3, 3, 3, 3, 4, 4, 4], [3, 3, 4, 4, 4, 4, 5, 5],
    [3, 3, 4, 4, 4, 4, 5, 5], [3, 4, 4, 4, 4, 4, 5, 5], [4, 4, 4, 4, 4, 5, 5, 5],
    [4, 4, 4, 4, 4, 5, 5, 5], [4, 4, 4, 5, 5, 5, 6, 6], [4, 4, 4, 5, 5, 5, 6, 6],
    [5, 5, 5, 5, 5, 6, 6, 7], [5, 6, 6, 6, 6, 7, 7, 7], [6, 6, 6, 7, 7, 7, 7, 8],
    [7, 7, 7, 7, 7, 8, 8, 8], [8, 8, 8, 8, 8, 9, 9, 9], [9, 9, 9, 9, 9, 9, 9, 9]
])

tableB_in = np.array([
    [1, 3, 2, 3, 3, 4, 5, 5, 6, 6, 7, 7], [2, 3, 2, 3, 4, 5, 5, 5, 6, 7, 7, 7],
    [3, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 7], [5, 5, 5, 6, 6, 7, 7, 7, 7, 7, 8, 8],
    [7, 7, 7, 7, 7, 8, 8, 8, 8, 8, 8, 8], [8, 8, 8, 8, 8, 8, 8, 9, 9, 9, 9, 9]
])

MUSCLE_USE  = 1   # repetitive desoldering task
LOAD_SCORE  = 0
LEG_SUPPORT = 2
ARM_SUPPORT = 0

NECK_AT_ZREF  = 25.0
TRUNK_AT_ZREF = 35.0
J_NECK        = 100.0
J_TRUNK       = 100.0


def rula_grand(sm_ua, sm_la, Z):
    neck  = max(0.0, NECK_AT_ZREF  + J_NECK  * (Z - Z_REF))
    trunk = max(0.0, TRUNK_AT_ZREF + J_TRUNK * (Z - Z_REF))

    up_sc = (1 if sm_ua <= 20 else 2 if sm_ua < 45 else 3 if sm_ua < 90 else 4)
    up_sc += ARM_SUPPORT
    lo_sc = 1 if 60 < sm_la < 100 else 2
    up_final = int(tableA_in[((up_sc - 1) * 3 + lo_sc) - 1, 0]) + MUSCLE_USE + LOAD_SCORE

    neck_sc  = 1 if neck  < 10 else (2 if neck  < 20 else 3)
    trunk_sc = 1 if trunk < 10 else (2 if trunk < 20 else 3 if trunk < 60 else 4)
    tn_sc = int(tableB_in[neck_sc - 1, (trunk_sc * 2 + LEG_SUPPORT) - 1])
    tn_sc += MUSCLE_USE + LOAD_SCORE
    return int(tableB_in[min(up_final, 6) - 1, min(tn_sc, 11) - 1])


# ── Optimizer parameters (verbatim from pcb_ergonomic_assistant.py) ───────────

IDEAL_UPPER   = 10.0;  IDEAL_LOWER  = 80.0
WEIGHT_UPPER  = 4.0;   WEIGHT_LOWER = 2.0
SIG_U_BELOW   = 20.0;  SIG_U_ABOVE  = 12.0;  PHUB_U = 1.0
SIG_L_BELOW   = 18.0;  SIG_L_ABOVE  = 18.0;  PHUB_L = 0.5
EMA_ALPHA     = 0.10;  JAC_EMA_ALPHA = 0.15
LEARNING_RATE = 0.0005
MIN_MOVE_THR  = 0.008   # 8 mm
MAX_STEP      = 0.010   # 10 mm
COOLDOWN_SEC  = 1.5
CYCLE_DT      = 0.10    # 10 Hz

STAB_LEN  = 12;  STAB_FRAC = 0.70
PLAT_LEN  = 15;  PLAT_THR  = 0.008

SAFE_LO_MIN = 60.0;  SAFE_LO_MAX = 100.0

# ── Noise & sway — AR(1) postural sway model ─────────────────────────────────
# Mochizuki et al. (2006) J Appl Biomech 22:51 — dominant sway f₀ = 0.40 Hz
# Carpenter et al. (2010) Gait Posture 32:380 — 90% of energy below 2 Hz
# ρ = exp(−2π f₀ / f_s) = exp(−2π × 0.40 / 10) = 0.778
NOISE_STD  = 3.0                                          # ° steady-state σ
AR1_RHO    = 0.78                                         # autocorrelation lag-1
AR1_SIG_W  = NOISE_STD * math.sqrt(1.0 - AR1_RHO ** 2)  # = 1.881 ° innovation

# ── Reach perturbations ───────────────────────────────────────────────────────
# Drury & Wick (1984) Ergonomics 27:187 — mean inter-reach 8–12 s → 10 s
# Rempel et al. (2006) Appl Ergon 37:735 — spikes 4–14°, return within 2–4 s
REACH_RATE    = CYCLE_DT / 10.0            # Poisson prob per 0.1 s cycle
REACH_MAG_LO  = 4.0                        # ° lower bound
REACH_MAG_HI  = 12.0                       # ° upper bound (excl. extreme outliers)
REACH_DECAY   = math.exp(-CYCLE_DT / 2.0)  # τ = 2 s → factor ≈ 0.951 per cycle

# ── Bilateral arm asymmetry ───────────────────────────────────────────────────
# Kee & Karwowski (2001) Ergonomics 44:1091 — tool hand 4–7° higher (mean 5.2°)
# Sadeghi et al. 2019 PeerJ 7:e8148 (PMC6908899) — non-dom sway ~30% larger
DOM_UA_MEAN    =  5.2;  DOM_UA_SD    = 3.1  # dominant (right) arm above neutral
NONDOM_UA_MEAN = -2.0;  NONDOM_UA_SD = 2.5  # non-dominant (left) arm below neutral
NONDOM_SWAY    =  1.30                       # sway scale factor for non-dominant arm

# ── Anthropometric per-trial variability ─────────────────────────────────────
# Pheasant & Haslegrave (2006) Bodyspace Table 3.2/3.4 — CoV ≈ 12% for Jacobians
# PEROSH (2018) §3.1 — inter-worker UA_REF SD ≈ 6°
# Chaffin et al. (2006) Occ. Biomechanics p.147 — LA SD ≈ 5° constrained tasks
J_UA_SD    = J_UA * 0.12       # 22.1 °/m
J_LA_SD    = abs(J_LA) * 0.12  # 16.8 °/m
UA_REF_SD  = 6.0               # °
LA_REF_SD  = 5.0               # °


def lower_dev(la):
    return max(0.0, SAFE_LO_MIN - la, la - SAFE_LO_MAX)


def aph(angle, opt, s_below, s_above, scale):
    d = angle - opt
    s = s_above if d >= 0.0 else s_below
    return scale * d / (s * s * math.sqrt(1.0 + (d / s) ** 2))


# ── Single trial ──────────────────────────────────────────────────────────────

def run_trial(Z_init, rng,
              ua_ref_r=None, ua_ref_l=None, la_ref_t=None,
              j_ua_t=None,   j_la_t=None,
              max_cycles=800):
    """
    Simulate one optimization trial with bilateral arm model and AR(1) sway.

    Parameters default to the nominal global constants (for backward
    compatibility when called without anthropometric arguments).

    Returns (t, moves, sm_ua_r, sm_ua_l, sm_la, Z_final, stop_reason)
    or None if max_cycles exceeded without convergence.
    """
    # Fall back to nominal constants if not supplied (single-arm legacy mode)
    if ua_ref_r is None: ua_ref_r = UA_REF
    if ua_ref_l is None: ua_ref_l = UA_REF
    if la_ref_t is None: la_ref_t = LA_REF
    if j_ua_t   is None: j_ua_t   = J_UA
    if j_la_t   is None: j_la_t   = J_LA

    Z = Z_init

    # Per-arm EMA state
    sm_ua_r = sm_ua_l = sm_la = None
    sm_ju   = sm_jl           = None

    stab_win = collections.deque(maxlen=STAB_LEN)
    plat_win = collections.deque(maxlen=PLAT_LEN)
    moves = []
    t = 0.0

    # AR(1) sway states (separate upper-arm sway per arm; shared elbow)
    sway_ua_r = sway_ua_l = sway_la = 0.0
    perturb_ua = 0.0   # shared reach perturbation — both arms move together

    for _ in range(max_cycles):
        t += CYCLE_DT

        # True joint angles at current Z for each arm
        ua_t_r, la_t = arm_angles(Z, ua_ref_r, la_ref_t, j_ua_t, j_la_t)
        ua_t_l, _    = arm_angles(Z, ua_ref_l, la_ref_t, j_ua_t, j_la_t)

        # ── AR(1) sway update ─────────────────────────────────────────────────
        # Mochizuki et al. 2006; Carpenter et al. 2010
        sway_ua_r = AR1_RHO * sway_ua_r + rng.normal(0.0, AR1_SIG_W)
        sway_ua_l = AR1_RHO * sway_ua_l + rng.normal(0.0, AR1_SIG_W * NONDOM_SWAY)
        sway_la   = AR1_RHO * sway_la   + rng.normal(0.0, AR1_SIG_W)

        # ── Reach perturbation ────────────────────────────────────────────────
        # Drury & Wick 1984; Rempel et al. 2006
        if rng.random() < REACH_RATE:
            perturb_ua += rng.uniform(REACH_MAG_LO, REACH_MAG_HI)
        perturb_ua *= REACH_DECAY

        raw_ua_r = max(0.0, ua_t_r + sway_ua_r + perturb_ua)
        raw_ua_l = max(0.0, ua_t_l + sway_ua_l + perturb_ua)
        raw_la   = max(0.0, la_t   + sway_la)

        # ── Per-arm EMA ───────────────────────────────────────────────────────
        sm_ua_r = (raw_ua_r if sm_ua_r is None
                   else EMA_ALPHA * raw_ua_r + (1 - EMA_ALPHA) * sm_ua_r)
        sm_ua_l = (raw_ua_l if sm_ua_l is None
                   else EMA_ALPHA * raw_ua_l + (1 - EMA_ALPHA) * sm_ua_l)
        sm_la   = (raw_la   if sm_la   is None
                   else EMA_ALPHA * raw_la   + (1 - EMA_ALPHA) * sm_la)

        # Worst arm drives the optimizer (current single-arm strategy)
        sm_ua_worst = max(sm_ua_r, sm_ua_l)

        # ── Jacobian EMA (per-trial constants + 5% frame noise) ───────────────
        Ju_n = j_ua_t * (1.0 + rng.normal(0.0, 0.05))
        Jl_n = j_la_t * (1.0 + rng.normal(0.0, 0.05))
        sm_ju = (Ju_n if sm_ju is None
                 else JAC_EMA_ALPHA * Ju_n + (1 - JAC_EMA_ALPHA) * sm_ju)
        sm_jl = (Jl_n if sm_jl is None
                 else JAC_EMA_ALPHA * Jl_n + (1 - JAC_EMA_ALPHA) * sm_jl)

        dC_dU = aph(sm_ua_worst, IDEAL_UPPER, SIG_U_BELOW, SIG_U_ABOVE, PHUB_U) * WEIGHT_UPPER
        dC_dL = aph(sm_la,       IDEAL_LOWER, SIG_L_BELOW, SIG_L_ABOVE, PHUB_L) * WEIGHT_LOWER
        z_raw = -LEARNING_RATE * (dC_dU * sm_ju + dC_dL * sm_jl)

        # ── Stability: BOTH arms must satisfy the in-zone criterion ───────────
        in_zone       = (raw_ua_r <= IDEAL_UPPER and raw_ua_l <= IDEAL_UPPER
                         and lower_dev(raw_la) == 0.0)
        stable_this   = in_zone or abs(z_raw) < MIN_MOVE_THR

        stab_win.append(stable_this)
        plat_win.append(abs(z_raw))

        win_full  = len(stab_win) == STAB_LEN
        stab_frac = sum(stab_win) / len(stab_win)
        plat_sum  = sum(plat_win)

        if len(plat_win) == PLAT_LEN and plat_sum < PLAT_THR:
            return t, moves, sm_ua_r, sm_ua_l, sm_la, Z, 'plateau'
        if win_full and stab_frac >= STAB_FRAC:
            return t, moves, sm_ua_r, sm_ua_l, sm_la, Z, 'stability'
        if stable_this:
            continue

        dz    = max(min(z_raw, MAX_STEP), -MAX_STEP)
        new_Z = max(min(Z + dz, Z_MAX), Z_MIN)
        act   = abs(new_Z - Z)
        if act < 0.001:
            continue

        t += COOLDOWN_SEC
        moves.append(act)
        Z = new_Z

    return None


# ── Monte Carlo ───────────────────────────────────────────────────────────────

def main():
    N   = 500
    rng = np.random.default_rng(42)

    times, move_counts, mean_steps = [], [], []
    final_ua_r, final_ua_l, final_las, final_scores = [], [], [], []
    init_scores = []
    plateau_n   = 0

    for _ in range(N):
        # ── Sample per-trial anthropometric parameters ────────────────────────
        # Pheasant & Haslegrave 2006; PEROSH 2018; Chaffin et al. 2006
        j_ua_t   = rng.normal(J_UA,    J_UA_SD)
        j_la_t   = rng.normal(J_LA,    J_LA_SD)    # J_LA negative; SD positive
        la_ref_t = rng.normal(LA_REF,  LA_REF_SD)

        ua_ref_nom = rng.normal(UA_REF, UA_REF_SD)  # operator-level neutral

        # Bilateral offsets (Kee & Karwowski 2001; PMC6908899)
        ua_ref_r = ua_ref_nom + rng.normal(DOM_UA_MEAN,    DOM_UA_SD)
        ua_ref_l = ua_ref_nom + rng.normal(NONDOM_UA_MEAN, NONDOM_UA_SD)

        Z0 = rng.uniform(0.55, 0.65)   # initial "too-high" workstation state

        ua0_r, la0 = arm_angles(Z0, ua_ref_r, la_ref_t, j_ua_t, j_la_t)
        ua0_l, _   = arm_angles(Z0, ua_ref_l, la_ref_t, j_ua_t, j_la_t)
        # Initial RULA: worst of both arms
        init_scores.append(max(rula_grand(ua0_r, la0, Z0),
                               rula_grand(ua0_l, la0, Z0)))

        res = run_trial(Z0, rng, ua_ref_r, ua_ref_l, la_ref_t, j_ua_t, j_la_t)
        if res is None:
            continue
        t, moves, ua_r, ua_l, la, Z_f, by = res
        times.append(t)
        move_counts.append(len(moves))
        mean_steps.append(np.mean(moves) * 1000 if moves else 0.0)
        final_ua_r.append(ua_r)
        final_ua_l.append(ua_l)
        final_las.append(la)
        # Final RULA: worst of both arms
        final_scores.append(max(rula_grand(ua_r, la, Z_f),
                                rula_grand(ua_l, la, Z_f)))
        if by == 'plateau':
            plateau_n += 1

    n = len(times)
    if n == 0:
        print("No trials converged — check kinematic model parameters.")
        return 1

    times        = np.array(times)
    move_counts  = np.array(move_counts, dtype=float)
    mean_steps   = np.array(mean_steps)
    final_ua_r   = np.array(final_ua_r)
    final_ua_l   = np.array(final_ua_l)
    final_las    = np.array(final_las)
    final_scores = np.array(final_scores)
    init_scores  = np.array(init_scores)

    pct_score_34 = 100 * np.mean((final_scores >= 3) & (final_scores <= 4))
    pct_ua_ok    = 100 * np.mean((final_ua_r <= 20) & (final_ua_l <= 20))
    pct_la_ok    = 100 * np.mean((final_las >= 60) & (final_las <= 100))
    plateau_pct  = 100 * plateau_n / n

    P = "\033[32mPASS\033[0m"
    F = "\033[31mFAIL\033[0m"

    def chk(label, val, lo, hi, unit=""):
        ok = lo <= val <= hi
        print(f"  [{ P if ok else F }]  {label:<52} {val:.1f}{unit}  [{lo}, {hi}]{unit}")
        return ok

    print("=" * 72)
    print(f"Optimizer Monte Carlo v2 (literature-calibrated) — {n}/{N} trials converged")
    print("=" * 72)
    print(f"\n  Initial RULA score (mean): {init_scores.mean():.1f}  (paper: 6–7)")
    print(f"  Final   RULA score (mean): {final_scores.mean():.1f}  (paper: 3–4)")
    print(f"\n  Final EMA angles (mean ± std):")
    print(f"    Right arm (dominant):    {final_ua_r.mean():.1f}° ± {final_ua_r.std():.1f}°")
    print(f"    Left arm (non-dominant): {final_ua_l.mean():.1f}° ± {final_ua_l.std():.1f}°")
    print(f"    Elbow:                   {final_las.mean():.1f}° ± {final_las.std():.1f}°  "
          f"(safe zone [60°, 100°])")
    print()

    passed = [
        chk("C6   % trials reaching RULA 3–4",           pct_score_34,      80, 100, "%"),
        chk("C7   % trials BOTH arms θ_ua ≤ 20°",         pct_ua_ok,         80, 100, "%"),
        chk("C8   % trials final θ_la in [60°, 100°]",    pct_la_ok,         80, 100, "%"),
        chk("C11  Mean convergence time",                  times.mean(),      20,  55, " s"),
        chk("     Mean move count",                        move_counts.mean(), 14,  32, ""),
        chk("     Mean step size",                         mean_steps.mean(), 4.0, 10.0, " mm"),
        chk("     Plateau-first rate",                     plateau_pct,        0,  50, "%"),
    ]

    print(f"\n  Time: mean={times.mean():.1f} s  std={times.std():.1f} s  "
          f"range=[{times.min():.1f}, {times.max():.1f}] s")
    print(f"  (paper: mean≈32.8 s, stated range 28–45 s)")

    print("\n" + "=" * 72)
    print(f"  {sum(passed)}/{len(passed)} checks passed")
    print("=" * 72)
    return 0 if all(passed) else 1


if __name__ == "__main__":
    sys.exit(main())
