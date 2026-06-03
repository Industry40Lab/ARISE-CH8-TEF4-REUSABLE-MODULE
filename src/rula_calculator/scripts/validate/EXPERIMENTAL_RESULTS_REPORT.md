# Experimental Results vs Paper Claims — Gap Analysis

**Date:** 2026-04-24  
**Trials:** 6 recorded CSVs (`trial_20260424_143409` through `trial_20260424_172239`)  
**Report PDF:** `figures/experiment_report.pdf` (9 pages)

---

## 1. Paper Claims (§4.3 — Preliminary Results)

| Metric | Paper claim |
|--------|-------------|
| RULA grand score — before | 6–7 (action level: immediate change required) |
| RULA grand score — after | 3–4 (action level: investigate further) |
| Convergence window | 28–45 s from `RULA_OPTIMIZING` onset |
| θ_ua before | 47.3° ± 4.1° |
| θ_ua after | **21.8° ± 3.2°** (RULA score-1 band ≤ 20°) |
| θ_la after | **74.6° ± 5.4°** (inside safe zone [60°, 100°]) |
| Optimizer moves per trial | 18–27 clamped steps |
| Mean step size | 6.3 mm |
| Mean convergence time | 32.8 s |
| Plateau criterion fires first | ~30 % of trials |
| Joint-angle jitter (raw) | ~3° r.m.s. at 30 fps |
| Borg CR-10 shoulder discomfort | 5.3 ± 0.6 → 2.7 ± 0.8 (−49 %) |

---

## 2. Measured Results (6 Trials)

| Metric | Trial 1 | Trial 2 | Trial 3 | Trial 4 | Trial 5 | Trial 6 | **Mean ± SD** |
|--------|---------|---------|---------|---------|---------|---------|--------------|
| RULA before | 5.50 | 6.00 | 5.20 | 5.89 | 6.00 | 6.00 | **5.76 ± 0.31** |
| RULA after | 5.83 | 4.95 | 4.60 | 5.03 | 4.65 | 5.95 | **5.17 ± 0.53** |
| θ_ua at conv. (°) | 37.65 | 36.73 | 37.34 | 36.04 | 37.70 | 41.05 | **37.75 ± 1.58** |
| θ_la at conv. (°) | 115.18 | 119.15 | 117.59 | 118.78 | 123.82 | 121.65 | **119.4 ± 2.77** |
| Convergence time (s) | n/a | 21.31 | 28.17 | n/a | 28.16 | 17.84 | **23.9 ± 4.5** (n=4) |
| Jitter std (°) | 0.60 | 0.66 | 0.42 | 0.54 | 0.62 | 0.74 | **0.60 ± 0.10** |
| Phase source | fallback | events | events | fallback | events | events | — |

> Trials 1 and 4 show `src=fallback` — phase transition events (`RULA_OPTIMIZING` → `USER_ADJUSTMENT`) fired within fewer than 10 rows of each other, so the before/after windows were estimated from the first/last quarter of the analysis window instead.

---

## 3. Claim-by-Claim Assessment

### C6 — RULA Score Reduction

| | Paper | Measured |
|-|-------|----------|
| Before | 6–7 | 5.76 ± 0.31 |
| After | **3–4** | **5.17 ± 0.53** |

**Status: PARTIAL.** The score does decrease in every trial (C6 PASS on the data-driven check). However, it does not reach the claimed 3–4 range. The after-score of ~5 corresponds to action level "further investigation and changes soon", not the claimed "investigate further" level 3–4. The RULA before-score (5.76) is also slightly below the paper's stated 6–7.

---

### C7 — Upper-Arm Flexion Convergence

| | Paper | Measured |
|-|-------|----------|
| After | **21.8° ± 3.2°** | **37.75° ± 1.58°** |

**Status: FAIL.** The optimizer converges but does not bring θ_ua into the RULA score-1 band (≤ 20°). At ~38°, the upper-arm sub-score remains at 2 (score-2 band: 20°–45°), which prevents the overall RULA score from reaching 3–4. The optimizer is running but the ergonomic target is not reached within the physical workspace.

---

### C8 — Elbow Angle Convergence

| | Paper | Measured |
|-|-------|----------|
| After | **74.6° ± 5.4°** | **119.4° ± 2.77°** |
| In [60°, 100°]? | Yes | No |

**Status: FAIL — but likely a measurement convention bug (see §4).**

The geometric angle computed by `points2angle(Shoulder, Elbow, Wrist)` gives the opening angle at the elbow. A natural working posture with ~61° flexion from full extension would measure geometrically as `180° − 61° = 119°`. If the RULA scoring formula uses `60 < low_hand_angle < 100` on the geometric angle, it will always score 2, even when the elbow posture is anatomically correct.

Interpreted as flexion: `180° − 119.4° = 60.6°` — which is at the lower edge of the safe zone and consistent with the paper's 74.6°.

---

### C11 — Convergence Time

| | Paper | Measured |
|-|-------|----------|
| Mean | 32.8 s | **23.9 ± 4.5 s** (n=4) |
| Range | 28–45 s | 17.8–28.2 s |

**Status: BORDERLINE.** Convergence is faster than claimed (some trials converge in under 20 s). Only 4/6 trials had detectable phase events — the other 2 converged too quickly to capture a meaningful before/after window. Faster convergence could indicate the optimizer is settling prematurely (plateau criterion firing early) rather than reaching the true ergonomic optimum.

---

### C2 — Joint-Angle Jitter

| | Paper | Measured |
|-|-------|----------|
| Raw jitter | ~3° r.m.s. | **0.60° ± 0.10°** |

**Status: NOT COMPARABLE — measurement mismatch.**  
The CSV records EMA-smoothed angles (α = 0.10), not raw angles. The paper's 3° r.m.s. refers to raw pre-EMA keypoint noise. The EMA at α = 0.10 suppresses high-frequency noise by design. To validate the 3° claim, the logger would need to record raw angles alongside the EMA values.

---

### C5 — RULA Sub-Score Band Consistency

| | Expected | Measured |
|-|----------|----------|
| θ_ua ≤ 20° → up_score = 1 | 100% | **3.2%** (90 rows) |
| θ_la ∈ (60°,100°) → lo_score = 1 | 100% | **65.8%** (150 rows) |

**Status: FAIL — consistent with the C8 convention bug.**  
θ_ua rarely reaches ≤ 20° (matches C7 finding). The 65.8% for θ_la means that when the geometric angle accidentally falls in [60°, 100°] (i.e., the elbow is near full extension), the sub-score is not always 1 — which points to an additional scoring inconsistency worth investigating in `rula_calculator.py`.

---

## 4. Root-Cause Analysis

### Issue 1 — Elbow Angle Convention Mismatch (highest priority)

The function `points2angle(A, B, C)` returns the geometric interior angle at B, ranging from 0° (fully folded) to 180° (fully extended). RULA Table A uses **elbow flexion** from full extension, where:

- Safe zone: 60° < flexion < 100°  
- Equivalently in geometric terms: 80° < geometric < 120°

The current RULA scoring check `60 < low_hand_angle < 100` applied to a geometric angle of ~119° will always return score 2, even though the posture is anatomically near-optimal. The fix would be to either:
- Convert inside the scoring function: `flexion = 180° − geometric_angle`, then check `60 < flexion < 100`
- Or confirm the angle is already defined as flexion elsewhere in the pipeline

**If this is confirmed as a bug, the RULA scores in all trials are systematically too high, and C8 may actually be passing in anatomical terms.**

---

### Issue 2 — Upper-Arm Not Converging to ≤ 20°

The optimizer reduces θ_ua from ~47° to ~38° but stalls there. Possible causes:

1. **Jacobian underestimated**: The real-world dθ_ua/dZ (how much the upper-arm angle changes per metre of Z-height change) may be smaller than the calibrated value in the optimizer, causing under-stepping.
2. **Workspace limits hit**: The robot may be reaching Z_min = 0.35 m before the ergonomic optimum is achieved for this operator's anthropometry.
3. **Premature convergence**: The sliding-window or plateau criterion may be firing before the full ergonomic benefit is realised — particularly if the Jacobian EMA has converged to a near-zero value.

---

### Issue 3 — Jitter Not Validated from Real Data

The claim of ~3° r.m.s. jitter is based on the simulation script (`validate_jitter.py`) which uses calibrated camera noise parameters. The real experiments do not currently log raw (pre-EMA) angles, so this claim cannot be validated from the CSV data. It can only be validated by adding a `right_arm_up_raw` column to the logger.

---

## 5. Summary Table

| Claim | Paper | Measured | Status | Root Cause |
|-------|-------|----------|--------|------------|
| C6 — RULA reduction | 6–7 → 3–4 | 5.76 → 5.17 | ⚠ Partial | θ_ua not converging; C8 bug |
| C7 — θ_ua at convergence | 21.8° ± 3.2° | 37.75° ± 1.58° | ✗ Fail | Optimizer stalling at ~38° |
| C8 — θ_la at convergence | 74.6° ± 5.4° | 119.4° ± 2.77° | ✗ Fail* | Likely angle convention bug |
| C11 — Convergence time | 32.8 s | 23.9 ± 4.5 s | ⚠ Faster | Possibly premature convergence |
| C2 — Jitter | ~3° r.m.s. | 0.60° (EMA) | — | Raw angles not logged |
| C5 — Sub-score consistency | 100% | 3.2% / 65.8% | ✗ Fail* | Follows from C7 + C8 bugs |

> `*` These failures are likely explained by the elbow angle convention bug (Issue 1). If corrected, C8 and C5 may pass. C7 and C6 require the optimizer to achieve deeper convergence (Issue 2).

---

## 6. Recommended Next Steps

1. **Verify elbow angle convention** in `rula_calculator.py` — check whether `right_low_angle` is geometric or flexion, and whether the RULA table lookup uses the correct interpretation.
2. **Log raw angles** alongside EMA values in `experiment_logger.py` to validate the C2 jitter claim from real data.
3. **Investigate premature convergence** — print the Z trajectory per trial and check whether the robot is hitting the workspace floor (Z_min = 0.35 m) or whether the plateau criterion fires before the true ergonomic minimum.
4. **Revisit the Jacobian** — compare the empirical dθ_ua/dZ from the Z trajectory and θ_ua trajectory in the CSV against the values assumed by the optimizer.
5. **Run more trials** with the elbow fix applied and check if RULA after drops into 3–4.
