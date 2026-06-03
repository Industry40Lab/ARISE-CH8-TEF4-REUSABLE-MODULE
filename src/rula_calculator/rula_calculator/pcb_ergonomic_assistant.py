import math
import rclpy
from rclpy.node import Node
import time
import collections
from enum import Enum, auto
from threading import Lock, Thread, Event
import rtde_control
import rtde_receive

from body_data.msg import BodyMsg
from std_msgs.msg import String


# ─── State machine ───────────────────────────────────────────────────────────
#
#   INIT
#    │  operator appears at all 3 cameras
#    ▼
#   RULA_OPTIMIZING  ◄─────────────────────────────────────────────────┐
#    │  sliding-window stable (≥90 % of 30 cycles)                     │
#    ▼                                                                  │
#   USER_ADJUSTMENT                                                     │
#    │  operator leaves and then reappears at all 3 cameras            │
#    └──────────────────────────────────────────────────────────────────┘
#
#  RULA_OPTIMIZING
#    • RULA gradient-descent runs every <cooldown> seconds.
#    • Requires all 3 cameras to see the operator (msg.left AND msg.right).
#    • THUMBS_UP / THUMBS_DOWN gestures are silently ignored.
#
#  USER_ADJUSTMENT
#    • Gradient-descent is NEVER called — the optimizer is completely inactive.
#    • THUMBS_UP  → raise end-effector 2 cm.
#    • THUMBS_DOWN → lower end-effector 2 cm.
#    • Operator leaving and returning → system re-enters RULA_OPTIMIZING.
#
# ─────────────────────────────────────────────────────────────────────────────

class Phase(Enum):
    INIT            = auto()
    RULA_OPTIMIZING = auto()
    USER_ADJUSTMENT = auto()


class OptimizationRTDEController(Node):

    def __init__(self):
        super().__init__('pcb_ergonomic_assistant')

        # ── ROS 2 parameters ────────────────────────────────────
        self.declare_parameter('robot_ip',              '192.168.0.100')
        self.declare_parameter('movement_cooldown_sec', 1.5)
        self.declare_parameter('z_min_limit',           0.35)
        self.declare_parameter('z_max_limit',           0.65)

        self.robot_ip = self.get_parameter('robot_ip').value
        self.cooldown = self.get_parameter('movement_cooldown_sec').value
        self.z_min    = self.get_parameter('z_min_limit').value
        self.z_max    = self.get_parameter('z_max_limit').value

        # ── Single lock protecting all mutable state ─────────────
        self._lock = Lock()

        # ── State machine ────────────────────────────────────────
        self._phase = Phase.INIT

        # ── Operator presence (all 3 cameras required) ───────────
        # "present" = BodyMsg received within timeout AND msg.left AND msg.right
        self._operator_present = False   # current presence state

        # ── Sensor data ──────────────────────────────────────────
        self._latest_msg    = None
        self._last_msg_time = 0.0
        self.data_timeout   = 1.5        # seconds before data is considered stale

        # ── EMA smoothing ────────────────────────────────────────
        self.ema_alpha           = 0.10   # strong smoothing reduces EMA lag near optimum
        self._smoothed_upper     = None
        self._smoothed_lower     = None
        # Jacobian EMA — slower alpha suppresses sign-flip oscillation from keypoint noise
        self.jac_ema_alpha       = 0.15
        self._smoothed_jac_upper = None
        self._smoothed_jac_lower = None

        # ── RULA ergonomic targets ───────────────────────────────
        # Optimal angles: centres of RULA score-1 zones (Chaffin et al. 2006)
        self.ideal_upper    = 10.0   # degrees — midpoint of [0°, 20°] bench-work neutral
        self.ideal_lower    = 80.0   # degrees — midpoint of [60°, 100°] safe elbow zone
        self.weight_upper   = 4.0
        self.weight_lower   = 2.0
        # Asymmetric pseudo-Huber shape parameters (Huber 1964; Peternel et al. 2019)
        # σ_above < σ_below → steeper cost when arm rises above optimal (biomechanical
        # asymmetry: deltoid moment arm decreases above ~30°, Hagberg 1981)
        self.upper_sigma_below = 20.0   # gentle slope below 10° (passive tissue support)
        self.upper_sigma_above = 12.0   # steep slope above 10° (active muscle load)
        self.upper_phub_scale  =  1.0
        self.lower_sigma_below = 18.0   # symmetric: RULA boundary at 60° = 80° − 20°
        self.lower_sigma_above = 18.0   # symmetric: RULA boundary at 100° = 80° + 20°
        self.lower_phub_scale  =  0.5
        # Keep for stability/exit criterion only (not cost):
        self.safe_lower_min = 60.0
        self.safe_lower_max = 100.0
        self.learning_rate  = 0.0005
        # Stability threshold is evaluated on the *unclamped* gradient offset so
        # that clamping to max_step does not mask a genuine ergonomic need.
        self.min_move_thr   = 0.008   # 8 mm — stable when unclamped gradient < this
        self.max_step       = 0.010   # 10 mm max per optimizer cycle

        # ── Sliding-window stability detector ───────────────────
        # 12 cycles × 100 ms = 1.2 s minimum fill time; 70 % → 9/12 stable
        self._stability_window    = collections.deque(maxlen=12)
        self.required_stable_frac = 0.70

        # ── Plateau detection ─────────────────────────────────────
        # Last 15 cycles' |z_offset| summed; if total Z movement < 8 mm
        # the optimizer is near-optimal but noise prevents stability criterion.
        self._plateau_window     = collections.deque(maxlen=15)
        self.plateau_threshold_m = 0.008  # 8 mm cumulative movement over 15 cycles

        # ── Gesture debounce ─────────────────────────────────────
        self.gesture_step       = 0.015  # metres per gesture (15 mm per tap)
        self.gesture_cooldown   = 0.7    # seconds between accepted gestures
        self._last_gesture_time = 0.0

        # ── Movement state ───────────────────────────────────────
        self._is_moving        = False
        self._last_action_time = time.time()
        self._pending_z        = 0.0
        self._pending_speed    = 0.02

        # ── RTDE reconnect ───────────────────────────────────────
        self._reconnect_attempts = 0
        self.max_reconnects      = 5

        # ── Cached TCP Z (polled in background, never on spin thread) ─────────
        self._cached_tcp_z = float('nan')

        # ── Async movement thread ────────────────────────────────
        self._move_event     = Event()
        self._shutdown_event = Event()
        self._move_thread       = Thread(target=self._movement_worker, daemon=True)
        self._rtde_poll_thread  = Thread(target=self._rtde_pose_loop,  daemon=True)

        # ── Connect to robot ─────────────────────────────────────
        self.get_logger().info(f"Connecting to UR5e at {self.robot_ip}…")
        try:
            self.rtde_c = rtde_control.RTDEControlInterface(self.robot_ip)
            self.rtde_r = rtde_receive.RTDEReceiveInterface(self.robot_ip)

            home = self.rtde_r.getActualTCPPose()
            home[2] = max(min(home[2], self.z_max), self.z_min)
            self.get_logger().info("Moving to safe home position…")
            self.rtde_c.moveL(home, 0.1, 0.5)   # blocking OK — not spinning yet

        except Exception as e:
            self.get_logger().error(f"Failed to connect to robot: {e}")
            raise

        self._move_thread.start()
        self._rtde_poll_thread.start()

        # ── ROS interfaces ───────────────────────────────────────
        self.create_subscription(BodyMsg, '/full_body_data',   self._cb_rula,    10)
        self.create_subscription(String,  '/operator_gesture', self._cb_gesture, 10)
        self._gui_pub = self.create_publisher(String, '/gui_notifications', 10)

        self.create_timer(0.1, self._control_loop)   # 10 Hz

        self._notify("System ready. Waiting for operator to appear at all 3 cameras…")
        self.get_logger().info("Waiting for operator presence at all 3 cameras.")

    # =========================================================================
    # STATE MACHINE
    # =========================================================================

    def _transition_to(self, new_phase: Phase, reason: str = ""):
        """Single entry point for all phase changes."""
        with self._lock:
            old_phase   = self._phase
            self._phase = new_phase

            if new_phase == Phase.RULA_OPTIMIZING:
                # Fresh start: clear all optimizer state.
                self._stability_window.clear()
                self._plateau_window.clear()
                self._smoothed_upper     = None
                self._smoothed_lower     = None
                self._smoothed_jac_upper = None
                self._smoothed_jac_lower = None

        tag = f"[{old_phase.name} → {new_phase.name}]"
        msg = f"{tag}  {reason}" if reason else tag
        self._notify(msg)
        self.get_logger().info(msg)

    def _rula_is_active(self) -> bool:
        with self._lock:
            return self._phase == Phase.RULA_OPTIMIZING

    def _gestures_are_active(self) -> bool:
        with self._lock:
            return self._phase == Phase.USER_ADJUSTMENT

    # =========================================================================
    # MOVEMENT THREAD
    # =========================================================================

    def _movement_worker(self):
        while not self._shutdown_event.is_set():
            if not self._move_event.wait(timeout=0.5):
                continue
            self._move_event.clear()

            with self._lock:
                target_z = self._pending_z
                speed    = self._pending_speed

            try:
                pose    = self.rtde_r.getActualTCPPose()
                pose[2] = target_z
                # Very gentle acceleration to avoid disturbing active desoldering work.
                accel   = max(0.003, speed * 0.8)
                self.get_logger().info(
                    f"moveL → Z={target_z:.3f} m  speed={speed:.4f} m/s  accel={accel:.4f} m/s²")
                self.rtde_c.moveL(pose, speed, accel)
                self._reconnect_attempts = 0

            except Exception as e:
                self.get_logger().error(f"RTDE moveL failed: {e}")
                self._handle_rtde_failure()

            finally:
                with self._lock:
                    self._is_moving        = False
                    self._last_action_time = time.time()

    def _trigger_move(self, z_target: float, speed: float) -> bool:
        with self._lock:
            if self._is_moving:
                return False
            self._is_moving     = True
            self._pending_z     = max(min(z_target, self.z_max), self.z_min)
            self._pending_speed = speed
        self._move_event.set()
        return True

    def _handle_rtde_failure(self):
        self._reconnect_attempts += 1
        if self._reconnect_attempts > self.max_reconnects:
            # Do NOT shut down — reset the counter and keep the node alive.
            # The background TCP poller (_rtde_pose_loop) will recover the
            # read channel automatically; the control channel reconnect is
            # retried on the next triggered move.
            self.get_logger().error(
                "Max RTDE reconnect attempts reached. Optimizer paused; "
                "will retry automatically when the robot connection recovers.")
            self._reconnect_attempts = 0
            return

        backoff = min(2.0 ** self._reconnect_attempts, 30.0)
        self.get_logger().warn(
            f"RTDE recovery {self._reconnect_attempts}/{self.max_reconnects} "
            f"in {backoff:.1f}s…")
        time.sleep(backoff)

        try:
            self.rtde_c.disconnect()
        except Exception:
            pass
        try:
            self.rtde_c.reconnect()
            self.get_logger().info("RTDE reconnected.")
        except Exception as e:
            self.get_logger().error(f"Reconnect failed: {e}")

    # =========================================================================
    # BACKGROUND TCP POSE POLLER  (never blocks the ROS spin thread)
    # =========================================================================

    def _rtde_pose_loop(self):
        """Poll TCP Z at 20 Hz in the background; cache under lock."""
        while not self._shutdown_event.is_set():
            try:
                pose = self.rtde_r.getActualTCPPose()
                with self._lock:
                    self._cached_tcp_z = float(pose[2])
            except Exception:
                pass
            time.sleep(0.05)

    def _get_tcp_z(self) -> float:
        with self._lock:
            return self._cached_tcp_z

    # =========================================================================
    # ROS CALLBACKS
    # =========================================================================

    def _cb_rula(self, msg: BodyMsg):
        with self._lock:
            self._latest_msg    = msg
            self._last_msg_time = time.time()

    def _cb_gesture(self, msg: String):
        """
        Only THUMBS_UP and THUMBS_DOWN are accepted.
        Both are valid ONLY in USER_ADJUSTMENT — silently dropped otherwise.
        """
        command = msg.data.upper()

        if command not in ('THUMBS_UP', 'THUMBS_DOWN'):
            return

        if not self._gestures_are_active():
            return   # RULA_OPTIMIZING or INIT — operator gestures ignored

        with self._lock:
            is_moving       = self._is_moving
            elapsed_gesture = time.time() - self._last_gesture_time

        if is_moving or elapsed_gesture < self.gesture_cooldown:
            return

        offset    = +self.gesture_step if command == 'THUMBS_UP' else -self.gesture_step
        direction = "UP"               if command == 'THUMBS_UP' else "DOWN"

        with self._lock:
            self._last_gesture_time = time.time()

        self._apply_gesture(offset, direction)

    # =========================================================================
    # CONTROL LOOP  (10 Hz)
    # =========================================================================

    def _control_loop(self):
        with self._lock:
            msg         = self._latest_msg
            msg_time    = self._last_msg_time
            is_moving   = self._is_moving
            last_action = self._last_action_time
            was_present = self._operator_present

        now        = time.time()
        data_fresh = msg is not None and (now - msg_time <= self.data_timeout)

        # Operator is "present" only when all 3 cameras detect them.
        # msg.left  = left  side camera has valid skeleton data
        # msg.right = right side camera has valid skeleton data
        # A BodyMsg being published at all means the front camera has data.
        currently_present = data_fresh and msg.left and msg.right

        # ── Update presence state ────────────────────────────────
        with self._lock:
            self._operator_present = currently_present

        # ── Presence transition handling ─────────────────────────
        if currently_present and not was_present:
            # Operator has (re)appeared at all 3 cameras.
            with self._lock:
                phase = self._phase

            if phase == Phase.INIT:
                self._transition_to(
                    Phase.RULA_OPTIMIZING,
                    "Operator detected at all 3 cameras. Starting RULA optimization.")
            elif phase == Phase.USER_ADJUSTMENT:
                self._transition_to(
                    Phase.RULA_OPTIMIZING,
                    "Operator reappeared at all 3 cameras. Restarting RULA optimization.")
            # If already RULA_OPTIMIZING, no transition needed.
            return   # give one cycle before running the optimizer

        if not currently_present:
            # Operator absent — pause optimizer, reset EMA.
            with self._lock:
                self._smoothed_upper = None
                self._smoothed_lower = None
            return

        # ── RULA optimizer gate ──────────────────────────────────
        # Only runs in RULA_OPTIMIZING. USER_ADJUSTMENT returns immediately.
        if not self._rula_is_active():
            return

        # ── Hard timeout check ───────────────────────────────────
        with self._lock:
            opt_start = self._optimization_start_time
        
        if now - opt_start > self.timeout:
            self._transition_to(
                Phase.USER_ADJUSTMENT,
                f"Optimizer timeout ({int(self.timeout)}s) reached. "
                "Switching to operator control.")
            return

        if is_moving or (now - last_action < self.cooldown):
            return

        # ── Plateau detection ─────────────────────────────────────
        with self._lock:
            plateau_window = list(self._plateau_window)

        if (len(plateau_window) == self._plateau_window.maxlen
                and sum(plateau_window) < self.plateau_threshold_m):
            self._transition_to(
                Phase.USER_ADJUSTMENT,
                "Optimizer plateau detected — cost function not improving. "
                "Switching to operator control.")
            return

        self._optimize_posture(msg)

    # =========================================================================
    # RULA GRADIENT-DESCENT OPTIMIZER
    # =========================================================================

    def _lower_deviation(self, angle: float) -> float:
        if angle < self.safe_lower_min:
            return self.safe_lower_min - angle
        if angle > self.safe_lower_max:
            return angle - self.safe_lower_max
        return 0.0

    def _asymmetric_pseudo_huber(self, angle: float, optimal: float,
                                  sigma_below: float, sigma_above: float,
                                  scale: float) -> float:
        """
        Returns ∂C/∂θ of the asymmetric pseudo-Huber cost.
        Quadratic near optimal, linear tails — gradient never vanishes at large deviations.
        sigma_above < sigma_below → steeper penalty when angle exceeds optimal.
        """
        d     = angle - optimal
        sigma = sigma_above if d >= 0.0 else sigma_below
        return scale * d / (sigma ** 2 * math.sqrt(1.0 + (d / sigma) ** 2))

    def _optimize_posture(self, msg: BodyMsg):
        # Both sides required — control loop already guarantees this via presence
        # check, but guard here as a safety net.
        if not msg.left or not msg.right:
            return

        # Worst-case upper arm angle (most raised side).
        raw_upper = max(msg.right_arm_up, msg.left_arm_up)
        # Elbow angle that deviates most from the safe range.
        raw_lower = sorted(
            [msg.right_low_angle, msg.left_low_angle],
            key=self._lower_deviation, reverse=True)[0]

        # Exponential Moving Average — smooths sensor noise before gradient step.
        with self._lock:
            if self._smoothed_upper is None:
                self._smoothed_upper = raw_upper
                self._smoothed_lower = raw_lower
            else:
                self._smoothed_upper = (self.ema_alpha * raw_upper
                                        + (1 - self.ema_alpha) * self._smoothed_upper)
                self._smoothed_lower = (self.ema_alpha * raw_lower
                                        + (1 - self.ema_alpha) * self._smoothed_lower)
            su, sl = self._smoothed_upper, self._smoothed_lower

        # Determine which side drives the optimization and its Jacobian.
        # du_dz is picked from the arm with the most flexion (most raised).
        if msg.right_arm_up > msg.left_arm_up:
            du_dz = msg.d_right_upper_dz
        else:
            du_dz = msg.d_left_upper_dz

        # dl_dz is picked from the arm that deviates most from the safe elbow range.
        if self._lower_deviation(msg.right_low_angle) > self._lower_deviation(msg.left_low_angle):
            dl_dz = msg.d_right_lower_dz
        else:
            dl_dz = msg.d_left_lower_dz

        # Drop frames where keypoint detection produced invalid Jacobians
        # (can occur during occlusion or AlphaPose confidence drops).
        if not (math.isfinite(du_dz) and math.isfinite(dl_dz)):
            return

        # Apply EMA to Jacobians — suppresses keypoint-noise sign flips that reverse gradient.
        with self._lock:
            if self._smoothed_jac_upper is None:
                self._smoothed_jac_upper = du_dz
                self._smoothed_jac_lower = dl_dz
            else:
                self._smoothed_jac_upper = (self.jac_ema_alpha * du_dz
                                            + (1 - self.jac_ema_alpha) * self._smoothed_jac_upper)
                self._smoothed_jac_lower = (self.jac_ema_alpha * dl_dz
                                            + (1 - self.jac_ema_alpha) * self._smoothed_jac_lower)
            du_dz = self._smoothed_jac_upper
            dl_dz = self._smoothed_jac_lower

        # Gradient of ergonomic cost w.r.t. angles — asymmetric pseudo-Huber.
        # Nonzero everywhere: no dead zones, no one-sided dropouts.
        dC_dU = self._asymmetric_pseudo_huber(
            su, self.ideal_upper,
            self.upper_sigma_below, self.upper_sigma_above,
            self.upper_phub_scale) * self.weight_upper

        dC_dL = self._asymmetric_pseudo_huber(
            sl, self.ideal_lower,
            self.lower_sigma_below, self.lower_sigma_above,
            self.lower_phub_scale) * self.weight_lower

        # Compute raw (unclamped) gradient step using the dynamic Jacobian.
        # Chain rule: dC/dZ = (dC/dU * dU/dZ) + (dC/dL * dL/dZ)
        z_offset_raw = -self.learning_rate * (dC_dU * du_dz + dC_dL * dl_dz)

        # ── Sliding-window stability check (on unclamped gradient) ───────────
        # raw_in_zone: raw angles already green regardless of EMA lag or Jacobian noise.
        raw_in_zone       = (raw_upper <= self.ideal_upper
                             and self._lower_deviation(raw_lower) == 0.0)
        stable_this_cycle = raw_in_zone or (abs(z_offset_raw) < self.min_move_thr)

        with self._lock:
            self._stability_window.append(stable_this_cycle)
            self._plateau_window.append(abs(z_offset_raw))
            window      = list(self._stability_window)
            window_full = len(window) == self._stability_window.maxlen

        stable_frac = sum(window) / len(window) if window else 0.0

        if window_full and stable_frac >= self.required_stable_frac:
            # ── PHASE TRANSITION: RULA_OPTIMIZING → USER_ADJUSTMENT ──────────
            self._transition_to(
                Phase.USER_ADJUSTMENT,
                "Ergonomic optimum reached. RULA optimizer paused.\n"
                "Use Thumbs Up / Down to fine-tune height.")
            return

        if stable_this_cycle:
            return   # gradient is negligible but window not full yet

        # ── Apply gradient step — clamped to max_step (3 mm) ─────────────────
        z_offset = max(min(z_offset_raw, self.max_step), -self.max_step)

        current_z = self._get_tcp_z()
        if math.isnan(current_z):
            return
        target_z      = max(min(current_z + z_offset, self.z_max), self.z_min)
        actual_offset = target_z - current_z

        if abs(actual_offset) < 0.001:   # sub-millimetre — skip
            return

        # Speed scales with displacement: min 10 mm/s, max 20 mm/s.
        speed     = max(0.010, min(0.020, abs(actual_offset) * 1.5))
        driver    = "shoulder strain" if abs(dC_dU) > abs(dC_dL) else "elbow posture"
        direction = "UP" if actual_offset > 0 else "DOWN"

        self._notify(
            f"Auto-optimizer: moving PCB {direction} "
            f"{abs(actual_offset)*100:.1f} cm to correct {driver}…")

        self._trigger_move(target_z, speed)

    # =========================================================================
    # GESTURE MOVEMENT  (USER_ADJUSTMENT only)
    # =========================================================================

    def _apply_gesture(self, offset: float, direction: str):
        current_z = self._get_tcp_z()
        if math.isnan(current_z):
            self._notify("TCP pose not yet available — please wait.")
            return
        target_z = max(min(current_z + offset, self.z_max), self.z_min)

        if abs(target_z - current_z) < 0.005:
            self._notify(f"Limit reached — cannot move {direction} any further.")
            return

        self._notify(f"Operator: adjusting PCB {direction} {abs(offset)*100:.1f} cm…")
        self._trigger_move(target_z, speed=0.025)

    # =========================================================================
    # UTILITIES
    # =========================================================================

    def _notify(self, message: str):
        gui_msg      = String()
        gui_msg.data = message
        self._gui_pub.publish(gui_msg)

    def destroy_node(self):
        self._shutdown_event.set()
        self._move_event.set()
        try:
            if hasattr(self, 'rtde_c') and self.rtde_c:
                self.rtde_c.disconnect()
            if hasattr(self, 'rtde_r') and self.rtde_r:
                self.rtde_r.disconnect()
        except Exception:
            pass
        finally:
            super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = OptimizationRTDEController()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
