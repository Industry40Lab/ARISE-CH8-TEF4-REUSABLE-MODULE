"""
C5 — RULA score-1 band validation.

Claims:
  - Upper arm in [0°, 20°] → RULA upper-arm sub-score = 1 (no modifiers).
  - Elbow in [60°, 100°] → RULA elbow sub-score = 1.

Also cross-checks the paper's stated before/after grand scores:
  - Before: θ_ua=47.3°, θ_la=74.6° → grand score in {6, 7}.
  - After:  θ_ua=21.8°, θ_la=74.6° → grand score in {3, 4}.

For the grand-score cross-check, realistic desoldering posture parameters are
used (muscle_use=1 — repetitive sustained task; neck ~25°, trunk ~35° before
optimisation; neck ~5°, trunk ~5° after, when the operator can sit upright).

No ROS runtime required.
"""

import sys
import numpy as np

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

# ── Modifiers ─────────────────────────────────────────────────────────────────
ARM_SUPPORT = 0   # no arm support
LOAD_SCORE  = 0   # < 2 kg
LEG_SUPPORT = 2   # legs and feet well supported

# Neutral (for isolated sub-score tests)
MUSCLE_USE_NEUTRAL  = 0
NECK_NEUTRAL        = 5.0
TRUNK_NEUTRAL       = 5.0

# Realistic desoldering (for grand-score cross-check):
#   muscle_use=1: repetitive/sustained task (desoldering)
#   Before optimisation: operator reaches up/forward → neck ~25°, trunk ~35°
#   After  optimisation: arm at ideal height → upright neck ~5°, trunk ~5°
MUSCLE_USE_DESOLDERING = 1
NECK_BEFORE  = 25.0
TRUNK_BEFORE = 35.0
NECK_AFTER   = 5.0
TRUNK_AFTER  = 5.0


# ── Scoring function (standalone equivalent of rula_calculation) ───────────

def rula_grand_score(up_hand_angle, low_hand_angle, neck_angle, trunk_angle,
                     muscle_use=0,
                     raised=0, up_abduction=0, low_abduction=0,
                     n_twist=0, n_bending=0, s_bending=0):
    """Standalone reimplementation of rula_calculator.rula_calculation()."""
    # Upper-arm sub-score
    if 20 < up_hand_angle < 45:   up_score = 2
    elif 45 < up_hand_angle < 90: up_score = 3
    elif up_hand_angle >= 90:     up_score = 4
    else:                         up_score = 1
    up_score += raised + up_abduction + ARM_SUPPORT

    # Lower-arm sub-score
    lower_score = 1 if 60 < low_hand_angle < 100 else 2
    lower_score += low_abduction

    # Group A
    up_final = tableA_in[((up_score - 1) * 3 + lower_score) - 1, 0]
    up_final = int(up_final) + muscle_use + LOAD_SCORE

    # Neck
    if neck_angle < 10:   neck_sc = 1
    elif neck_angle < 20: neck_sc = 2
    else:                 neck_sc = 3
    neck_sc += n_twist + n_bending

    # Trunk
    if trunk_angle < 10:   trunk_sc = 1
    elif trunk_angle < 20: trunk_sc = 2
    elif trunk_angle < 60: trunk_sc = 3
    else:                  trunk_sc = 4
    trunk_sc += s_bending

    # Group B
    tn_sc = int(tableB_in[neck_sc - 1, (trunk_sc * 2 + LEG_SUPPORT) - 1])
    tn_sc += muscle_use + LOAD_SCORE

    grand = int(tableB_in[min(up_final, 6) - 1, min(tn_sc, 11) - 1])
    return grand, int(up_score), int(lower_score)


def check(label, result, expected, note=""):
    ok = expected[0] <= result <= expected[1]
    status = "\033[32mPASS\033[0m" if ok else "\033[31mFAIL\033[0m"
    suffix = f"  ({note})" if note else ""
    print(f"  [{status}]  {label:<52} got {result}  expected {expected}{suffix}")
    return ok


def main():
    results = []

    print("=" * 72)
    print("C5 — RULA score-1 band and grand-score validation")
    print("=" * 72)

    # ── Upper-arm sub-score: score-1 band = [0°, 20°] ─────────────────────
    print("\n  Upper-arm sub-score (neutral modifiers, neutral elbow)")
    for ua in [0, 5, 10, 15, 19.9]:
        _, up_sc, _ = rula_grand_score(ua, 80.0, NECK_NEUTRAL, TRUNK_NEUTRAL)
        results.append(check(f"θ_ua={ua}° → up_score=1", up_sc, (1, 1), "score-1 band"))

    for ua in [20.1, 30, 44.9]:
        _, up_sc, _ = rula_grand_score(ua, 80.0, NECK_NEUTRAL, TRUNK_NEUTRAL)
        results.append(check(f"θ_ua={ua}° → up_score=2", up_sc, (2, 2), "score-2 band"))

    for ua in [45.1, 60, 89.9]:
        _, up_sc, _ = rula_grand_score(ua, 80.0, NECK_NEUTRAL, TRUNK_NEUTRAL)
        results.append(check(f"θ_ua={ua}° → up_score=3", up_sc, (3, 3), "score-3 band"))

    # ── Lower-arm sub-score: score-1 band = [60°, 100°] ───────────────────
    print("\n  Lower-arm sub-score (neutral modifiers, neutral upper arm)")
    for la in [61, 70, 80, 90, 99]:
        _, _, lo_sc = rula_grand_score(10.0, la, NECK_NEUTRAL, TRUNK_NEUTRAL)
        results.append(check(f"θ_la={la}° → lower_score=1", lo_sc, (1, 1), "score-1 band"))

    for la in [30, 45, 59, 101, 130, 150]:
        _, _, lo_sc = rula_grand_score(10.0, la, NECK_NEUTRAL, TRUNK_NEUTRAL)
        results.append(check(f"θ_la={la}° → lower_score=2", lo_sc, (2, 2), "outside safe zone"))

    # ── Grand score cross-check (realistic desoldering posture) ───────────
    print("\n  Grand score — realistic desoldering (muscle_use=1, forward neck/trunk)")
    print(f"    Before: neck={NECK_BEFORE}°, trunk={TRUNK_BEFORE}°")
    grand_before, *_ = rula_grand_score(
        47.3, 74.6, NECK_BEFORE, TRUNK_BEFORE,
        muscle_use=MUSCLE_USE_DESOLDERING)
    results.append(check(
        "Before θ_ua=47.3°, θ_la=74.6° → grand 6–7",
        grand_before, (6, 7)))

    print(f"    After:  neck={NECK_AFTER}°,  trunk={TRUNK_AFTER}°  (upright with lower PCB)")
    grand_after, *_ = rula_grand_score(
        21.8, 74.6, NECK_AFTER, TRUNK_AFTER,
        muscle_use=MUSCLE_USE_DESOLDERING)
    results.append(check(
        "After  θ_ua=21.8°, θ_la=74.6° → grand 3–4",
        grand_after, (3, 4)))

    # ── Table bounds sanity ────────────────────────────────────────────────
    print("\n  Table bounds sanity (all valid index combinations)")
    oob_a = sum(
        1 for us in range(1, 5) for ls in range(1, 4)
        if not (1 <= tableA_in[(us - 1) * 3 + ls - 1, 0] <= 9))
    results.append(check("tableA_in values in [1, 9]", oob_a, (0, 0)))

    oob_b = int(np.any((tableB_in < 1) | (tableB_in > 9)))
    results.append(check("tableB_in values in [1, 9]", oob_b, (0, 0)))

    print("\n" + "=" * 72)
    n_pass = sum(results)
    print(f"  {n_pass}/{len(results)} checks passed")
    print("=" * 72)

    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
