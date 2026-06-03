# PCB Ergonomic Assistant — Mathematical Description

---

## 1. Sensor-to-Angle Pipeline (rula_calculator.py)

### 1.1 Input Keypoints

Three 3-D points per arm are extracted from the RealSense skeleton:

- **S** — Shoulder  
- **E** — Elbow  
- **W** — Wrist  

Camera frame convention: **+Y points downward** (gravity direction).

---

### 1.2 Upper Arm Angle

The upper arm angle is the flexion of the upper arm relative to the vertical-down direction.

Let:

$$\vec{SW} = W - S, \quad r = \|\vec{SW}\|$$

$$\hat{u}_{SW} = \frac{\vec{SW}}{r}$$

Angle of the shoulder-to-wrist vector relative to gravity:

$$\theta_{SW} = \arccos\!\left(\hat{u}_{SW} \cdot \begin{bmatrix}0\\1\\0\end{bmatrix}\right)$$

Angle at S in triangle S–E–W (Law of Cosines), with limb lengths $L_1 = \|E - S\|$, $L_2 = \|W - E\|$:

$$\beta = \arccos\!\left(\frac{L_1^2 + r^2 - L_2^2}{2\,L_1\,r}\right)$$

Upper arm flexion angle:

$$\boxed{\theta_\text{upper} = \theta_{SW} - \beta}$$

---

### 1.3 Lower Arm (Elbow) Angle

Interior angle at the elbow joint (Law of Cosines):

$$r = \min(r,\ 0.99\,(L_1 + L_2)) \quad \text{(singularity guard)}$$

$$\boxed{\theta_\text{lower} = \arccos\!\left(\frac{L_1^2 + L_2^2 - r^2}{2\,L_1\,L_2}\right)}$$

---

### 1.4 Numerical Jacobian (Sensitivity to Robot Z-Height)

The relationship between the robot's end-effector height $Z$ and camera $Y$ is:

$$\frac{\partial}{\partial Z} = -\frac{\partial}{\partial Y_\text{cam}}$$

The wrist is perturbed by $\delta y = 1\,\text{mm}$ in camera $Y$:

$$W_{\delta} = W + \begin{bmatrix}0\\\delta y\\0\end{bmatrix}$$

Numerical derivatives:

$$\frac{\partial\theta_\text{upper}}{\partial Y_\text{cam}} = \frac{\theta_\text{upper}(W_\delta) - \theta_\text{upper}(W)}{\delta y}$$

$$\frac{\partial\theta_\text{lower}}{\partial Y_\text{cam}} = \frac{\theta_\text{lower}(W_\delta) - \theta_\text{lower}(W)}{\delta y}$$

Converting to robot Z (sign flip):

$$\boxed{\frac{\partial\theta_\text{upper}}{\partial Z} = -\frac{\partial\theta_\text{upper}}{\partial Y_\text{cam}}, \qquad \frac{\partial\theta_\text{lower}}{\partial Z} = -\frac{\partial\theta_\text{lower}}{\partial Y_\text{cam}}}$$

These are published in `BodyMsg` as `d_*_upper_dz` and `d_*_lower_dz`.

---

## 2. Signal Smoothing (pcb_ergonomic_assistant.py)

### 2.1 Angle EMA

Exponential Moving Average applied to raw angle measurements ($\alpha = 0.10$):

$$\boxed{\tilde{\theta}_{k} = \alpha\,\theta^\text{raw}_{k} + (1-\alpha)\,\tilde{\theta}_{k-1}}$$

The worst-case (driving) side is selected before smoothing:

$$\theta^\text{raw}_\text{upper} = \max(\theta^\text{right}_\text{upper},\ \theta^\text{left}_\text{upper})$$

$$\theta^\text{raw}_\text{lower} = \underset{\theta \in \{\theta^\text{right}_\text{lower},\,\theta^\text{left}_\text{lower}\}}{\arg\max}\ d_\text{lower}(\theta)$$

where $d_\text{lower}$ is the lower-arm deviation function defined in Section 3.1.

### 2.2 Jacobian EMA

Same structure applied to each Jacobian element ($\alpha_J = 0.15$):

$$\boxed{\widetilde{J}_{k} = \alpha_J\,J^\text{raw}_{k} + (1-\alpha_J)\,\widetilde{J}_{k-1}}$$

The slower $\alpha_J$ suppresses keypoint-noise sign flips that would reverse the gradient direction.

---

## 3. Ergonomic Cost Function

### 3.1 Lower-Arm Deviation

$$d_\text{lower}(\theta) = \begin{cases} \theta_{\min} - \theta & \text{if } \theta < \theta_{\min} \\ \theta - \theta_{\max} & \text{if } \theta > \theta_{\max} \\ 0 & \text{otherwise} \end{cases}$$

with $\theta_{\min} = 60°$ and $\theta_{\max} = 100°$.

### 3.2 Cost Function

$$\boxed{C(\tilde{\theta}_\text{upper},\,\tilde{\theta}_\text{lower}) = w_U\,\bigl[\max(0,\,\tilde{\theta}_\text{upper} - \theta^*_U)\bigr]^2 + w_L\,\bigl[d_\text{lower}(\tilde{\theta}_\text{lower})\bigr]^2}$$

| Symbol | Value | Meaning |
|--------|-------|---------|
| $\theta^*_U$ | 20° | Ideal upper-arm angle |
| $w_U$ | 4.0 | Upper-arm cost weight |
| $w_L$ | 1.0 | Lower-arm cost weight |

The upper-arm term is **one-sided**: no penalty when the upper arm is below the ideal.

---

## 4. Gradient-Descent Optimizer

### 4.1 Cost Gradients w.r.t. Angles

$$\frac{\partial C}{\partial \tilde{\theta}_U} = \begin{cases} 2\,w_U\,(\tilde{\theta}_U - \theta^*_U) & \text{if } \tilde{\theta}_U > \theta^*_U \\ 0 & \text{otherwise} \end{cases}$$

$$\frac{\partial C}{\partial \tilde{\theta}_L} = \begin{cases} -2\,w_L\,(\theta_{\min} - \tilde{\theta}_L) & \text{if } \tilde{\theta}_L < \theta_{\min} \\ +2\,w_L\,(\tilde{\theta}_L - \theta_{\max}) & \text{if } \tilde{\theta}_L > \theta_{\max} \\ 0 & \text{otherwise} \end{cases}$$

### 4.2 Chain Rule — Gradient w.r.t. Robot Z

$$\frac{\partial C}{\partial Z} = \frac{\partial C}{\partial \tilde{\theta}_U}\,\widetilde{J}_U + \frac{\partial C}{\partial \tilde{\theta}_L}\,\widetilde{J}_L$$

### 4.3 Gradient-Descent Step (unclamped)

$$\boxed{\Delta Z^\text{raw} = -\eta\,\frac{\partial C}{\partial Z}}$$

with learning rate $\eta = 5 \times 10^{-4}$ m/°·(weight unit).

### 4.4 Step Clamping

$$\Delta Z = \text{clip}\!\left(\Delta Z^\text{raw},\ -\Delta Z_{\max},\ +\Delta Z_{\max}\right), \quad \Delta Z_{\max} = 10\,\text{mm}$$

### 4.5 Target Height and Safety Bounds

$$Z_\text{target} = \text{clip}\!\left(Z_\text{current} + \Delta Z,\ Z_{\min},\ Z_{\max}\right)$$

$$Z_{\min} = 0.35\,\text{m}, \quad Z_{\max} = 0.65\,\text{m}$$

### 4.6 Movement Speed

Speed scales linearly with displacement:

$$v = \text{clip}\!\left(1.5\,|\Delta Z_\text{actual}|,\ 10\,\text{mm/s},\ 20\,\text{mm/s}\right)$$

$$a = \max(3\,\text{mm/s}^2,\ 0.8\,v)$$

---

## 5. Convergence Detection

### 5.1 Per-Cycle Stability Flag

A cycle is marked **stable** when either of the following holds:

1. Raw angles are already in the ergonomic zone:  
   $\theta^\text{raw}_\text{upper} \le \theta^*_U$ **and** $d_\text{lower}(\theta^\text{raw}_\text{lower}) = 0$

2. The unclamped gradient step is negligible:  
   $|\Delta Z^\text{raw}| < \delta_\text{stable}$, with $\delta_\text{stable} = 8\,\text{mm}$

### 5.2 Sliding-Window Stability Exit

Let $\mathcal{W}$ be the last $N = 12$ stability flags. The optimizer exits to USER_ADJUSTMENT when:

$$\frac{1}{N}\sum_{i=1}^{N} \mathbf{1}[\text{stable}_i] \;\ge\; f_\text{stable} = 0.70$$

### 5.3 Plateau Exit (Fallback)

If the cumulative absolute Z movement over the last $M = 15$ cycles is negligibly small, the optimizer has stalled near a local minimum:

$$\sum_{i=1}^{M} |\Delta Z^\text{raw}_i| < \delta_\text{plateau} = 8\,\text{mm}$$

---

## 6. Parameter Summary

| Parameter | Symbol | Value |
|-----------|--------|-------|
| Ideal upper-arm angle | $\theta^*_U$ | 20° |
| Safe lower-arm range | $[\theta_{\min}, \theta_{\max}]$ | [60°, 100°] |
| Upper-arm cost weight | $w_U$ | 4.0 |
| Lower-arm cost weight | $w_L$ | 1.0 |
| Learning rate | $\eta$ | 5 × 10⁻⁴ |
| Max step per cycle | $\Delta Z_{\max}$ | 10 mm |
| Stability threshold | $\delta_\text{stable}$ | 8 mm |
| Stability fraction | $f_\text{stable}$ | 0.70 |
| Stability window size | $N$ | 12 cycles |
| Plateau window size | $M$ | 15 cycles |
| Plateau threshold | $\delta_\text{plateau}$ | 8 mm |
| Angle EMA alpha | $\alpha$ | 0.10 |
| Jacobian EMA alpha | $\alpha_J$ | 0.15 |
| Control loop rate | — | 10 Hz |
| Movement cooldown | — | 1.5 s |
| Z safety bounds | $[Z_{\min}, Z_{\max}]$ | [0.35, 0.65] m |
| Gesture step | — | 15 mm |
