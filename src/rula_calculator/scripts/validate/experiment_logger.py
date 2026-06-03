"""
experiment_logger — ROS 2 node that records a live trial to CSV.

Subscribes to:
  /full_body_data    (body_data/BodyMsg)   — joint angles and RULA scores
  /gui_notifications (std_msgs/String)     — phase-transition events
  /operator_gesture  (std_msgs/String)     — THUMBS_UP / THUMBS_DOWN / NONE

RTDE is polled at 2 Hz in a separate daemon thread so it never competes with
the ROS spin loop or the camera pipeline.  Use -p dry_run:=true to skip RTDE.

Usage:
  export ROS_DOMAIN_ID=0
  ros2 run rula_calculator experiment_logger \\
    --ros-args -p robot_ip:=192.168.0.100 \\
               -p output_file:=/tmp/trial_$(date +%Y%m%d_%H%M%S).csv
"""

import csv
import math
import os
import time
from collections import deque
from threading import Event, Lock, Thread

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from body_data.msg import BodyMsg

CSV_COLUMNS = [
    'timestamp_s',
    'right_arm_up', 'left_arm_up',
    'right_low_angle', 'left_low_angle',
    'neck_angle', 'trunk_angle',
    'right_rula_score', 'left_rula_score',
    'up_arm_score_right', 'up_arm_score_left',
    'lower_arm_score_right', 'lower_arm_score_left',
    'tcp_z_m',
    'phase_event',
    'gesture',
]

RTDE_POLL_HZ = 2   # low rate — TCP Z changes slowly; keeps CPU free for cameras


class ExperimentLogger(Node):

    def __init__(self):
        super().__init__('experiment_logger')

        self.declare_parameter('robot_ip',    '192.168.0.100')
        self.declare_parameter('output_file', '/tmp/trial.csv')
        self.declare_parameter('dry_run',     False)

        robot_ip    = self.get_parameter('robot_ip').value
        output_file = self.get_parameter('output_file').value
        dry_run     = self.get_parameter('dry_run').value

        self._lock         = Lock()
        self._tcp_z        = float('nan')
        self._phase_events = deque()   # accumulate; never overwrite
        self._gestures     = deque()
        self._stop         = Event()

        # ── RTDE — plain daemon thread, fully off the ROS executor ───────────
        self._rtde_r = None
        if not dry_run:
            try:
                import rtde_receive
                self._rtde_r = rtde_receive.RTDEReceiveInterface(robot_ip)
                self.get_logger().info(f'RTDE connected to {robot_ip}')
                t = Thread(target=self._rtde_loop, daemon=True)
                t.start()
            except Exception as exc:
                self.get_logger().warn(
                    f'RTDE unavailable ({exc}); tcp_z_m = NaN. '
                    f'Use -p dry_run:=true to suppress.')
        else:
            self.get_logger().info('Dry-run — RTDE disabled, tcp_z_m = NaN')

        # ── CSV ───────────────────────────────────────────────────────────────
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
        self._csv_file = open(output_file, 'w', newline='')
        self._writer   = csv.DictWriter(self._csv_file, fieldnames=CSV_COLUMNS)
        self._writer.writeheader()
        self._csv_file.flush()
        self.get_logger().info(f'Logging to {output_file}')

        # ── Subscriptions — match publisher QoS (RELIABLE, VOLATILE, depth=10)
        self.create_subscription(BodyMsg, '/full_body_data',    self._body_cb,    10)
        self.create_subscription(String,  '/gui_notifications', self._gui_cb,     10)
        self.create_subscription(String,  '/operator_gesture',  self._gesture_cb, 10)

    # ── RTDE daemon thread ────────────────────────────────────────────────────

    def _rtde_loop(self):
        interval = 1.0 / RTDE_POLL_HZ
        while not self._stop.is_set():
            try:
                pose = self._rtde_r.getActualTCPPose()
                with self._lock:
                    self._tcp_z = float(pose[2])
            except Exception:
                with self._lock:
                    self._tcp_z = float('nan')
            time.sleep(interval)

    # ── ROS callbacks (all on the single spin thread) ─────────────────────────

    def _gui_cb(self, msg: String):
        with self._lock:
            self._phase_events.append(msg.data.strip())

    def _gesture_cb(self, msg: String):
        with self._lock:
            self._gestures.append(msg.data.strip())

    def _body_cb(self, msg: BodyMsg):
        t = self.get_clock().now().nanoseconds * 1e-9

        with self._lock:
            tcp_z       = self._tcp_z
            phase_event = '; '.join(self._phase_events)
            gesture     = '; '.join(self._gestures)
            self._phase_events.clear()
            self._gestures.clear()

        row = {
            'timestamp_s':           f'{t:.4f}',
            'right_arm_up':          f'{msg.right_arm_up:.2f}',
            'left_arm_up':           f'{msg.left_arm_up:.2f}',
            'right_low_angle':       f'{msg.right_low_angle:.2f}',
            'left_low_angle':        f'{msg.left_low_angle:.2f}',
            'neck_angle':            f'{msg.neck_angle:.2f}',
            'trunk_angle':           f'{msg.trunk_angle:.2f}',
            'right_rula_score':      str(msg.right_rula_score),
            'left_rula_score':       str(msg.left_rula_score),
            'up_arm_score_right':    str(msg.up_arm_score_right),
            'up_arm_score_left':     str(msg.up_arm_score_left),
            'lower_arm_score_right': str(msg.lower_arm_score_right),
            'lower_arm_score_left':  str(msg.lower_arm_score_left),
            'tcp_z_m':               'nan' if math.isnan(tcp_z) else f'{tcp_z:.4f}',
            'phase_event':           phase_event,
            'gesture':               gesture,
        }
        self._writer.writerow(row)
        self._csv_file.flush()

    def destroy_node(self):
        self._stop.set()
        self._csv_file.close()
        if self._rtde_r is not None:
            try:
                self._rtde_r.disconnect()
            except Exception:
                pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = ExperimentLogger()
    try:
        rclpy.spin(node)          # single-threaded — no CPU competition
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
