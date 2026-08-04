"""Headless pressure-risk monitoring client for Raspberry Pi 5.

Reads pressure frames over serial (same protocol as sensor recorder),
accumulates per-cell risk over real elapsed time, and reports cells that
stay risky past `critical_time` to a server, subject to a per-cell alert
cooldown. The three risk thresholds (calibration_factor, critical_pressure,
critical_time) are polled periodically from the server, as are pending
monitor commands (start/pause/stop/reset/state).

Usage:
    python -m client.main [--port /dev/ttyUSB0] [--baud 921600]
                           [--cols 32] [--rows 64] [--header A55A]
                           [--pre 6] [--post 2]
                           [--server-url http://localhost:5000]
                           [--poll-interval 60] [--command-poll-interval 2]
                           [--http-timeout 5] [--alert-cooldown 300]
                           [--dry-run] [--dry-fps 30]
"""
import argparse
import os
import signal
import sys
import threading
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import numpy as np  # noqa: E402

from sensor.frame_parser import FrameParser  # noqa: E402
from sensor.serial_reader import SerialReader  # noqa: E402

from client.config import ClientConfig, RuntimeConfig  # noqa: E402
from client.http_client import CommandPoller, ConfigPoller, EventSender, StateSender  # noqa: E402
from client.monitor import MonitorState  # noqa: E402
from client.risk import RiskAccumulator  # noqa: E402

DEFAULT_PORT = "/dev/ttyUSB0"


def build_parser():
    p = argparse.ArgumentParser(prog="client.main", description="Pressure risk monitoring client")
    p.add_argument("--port", default=DEFAULT_PORT, help=f"Serial port (default: {DEFAULT_PORT})")
    p.add_argument("--baud", type=int, default=ClientConfig.baud)
    p.add_argument("--cols", type=int, default=ClientConfig.cols)
    p.add_argument("--rows", type=int, default=ClientConfig.rows)
    p.add_argument("--header", default=ClientConfig.header_hex, help="hex string, e.g. A55A")
    p.add_argument("--pre", type=int, default=ClientConfig.pre_skip)
    p.add_argument("--post", type=int, default=ClientConfig.post_skip)
    p.add_argument("--server-url", default=ClientConfig.server_base_url)
    p.add_argument("--config-path", default=ClientConfig.config_path)
    p.add_argument("--event-path", default=ClientConfig.event_path)
    p.add_argument("--command-path", default=ClientConfig.command_path)
    p.add_argument("--state-path", default=ClientConfig.state_path)
    p.add_argument("--poll-interval", type=float, default=ClientConfig.poll_interval_s)
    p.add_argument("--command-poll-interval", type=float,
                    default=ClientConfig.command_poll_interval_s)
    p.add_argument("--http-timeout", type=float, default=ClientConfig.http_timeout_s)
    p.add_argument("--http-retry-delay", type=float, default=ClientConfig.http_retry_delay_s)
    p.add_argument("--alert-cooldown", type=float, default=ClientConfig.alert_cooldown_s)
    p.add_argument("--pressure-mask-threshold", type=int,
                    default=ClientConfig.pressure_mask_threshold)
    p.add_argument("--dry-run", action="store_true",
                    help="generate synthetic frames instead of reading the serial port")
    p.add_argument("--dry-fps", type=float, default=30.0)
    return p


class FakeReader:
    """Synthetic frame producer for --dry-run. Mimics SerialReader.start/stop.
    A small hot-spot region is always saturated so --dry-run exercises the
    full risk -> alert path without needing real hardware."""

    def __init__(self, cols, rows, fps, on_frame, on_status=None):
        self.cols = cols
        self.rows = rows
        self.period = 1.0 / max(fps, 1e-3)
        self.on_frame = on_frame
        self.on_status = on_status or (lambda connected, msg: None)
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None

    def _run(self):
        self.on_status(True, "Dry-run: synthetic frames")
        while not self._stop.is_set():
            frame = np.random.randint(0, 40, size=(self.rows, self.cols), dtype=np.uint8)
            frame[0:2, 0:2] = 255  # persistent hot spot
            try:
                self.on_frame(time.time(), frame)
            except Exception:
                pass
            if self._stop.wait(self.period):
                break
        self.on_status(False, "Dry-run: stopped")


class LatestFrame:
    """Thread-safe holder for the most recently received (timestamp,
    pressure_vector) pair, used to answer `state` commands regardless of
    whether risk accumulation is currently active."""

    def __init__(self):
        self._lock = threading.Lock()
        self._ts = None
        self._pressure_vector = None

    def set(self, ts, pressure_vector):
        with self._lock:
            self._ts = ts
            self._pressure_vector = pressure_vector

    def get(self):
        with self._lock:
            return self._ts, self._pressure_vector


class ClientApp:
    def __init__(self, args):
        self.args = args
        self.stop_event = threading.Event()
        n_cells = args.cols * args.rows

        self.runtime_config = RuntimeConfig()
        self.risk_acc = RiskAccumulator(n_cells, alert_cooldown_s=args.alert_cooldown)
        self.monitor = MonitorState(self.risk_acc)
        self.latest_frame = LatestFrame()

        self.poller = ConfigPoller(
            args.server_url, args.config_path, args.poll_interval,
            self.runtime_config, timeout_s=args.http_timeout, on_status=self.on_poll_status,
        )
        self.command_poller = CommandPoller(
            args.server_url, args.command_path, args.command_poll_interval,
            self.on_command, timeout_s=args.http_timeout, on_status=self.on_command_status,
        )
        self.sender = EventSender(
            args.server_url, args.event_path, timeout_s=args.http_timeout,
            retry_delay_s=args.http_retry_delay, on_status=self.on_send_status,
        )
        self.state_sender = StateSender(
            args.server_url, args.state_path, timeout_s=args.http_timeout,
            retry_delay_s=args.http_retry_delay, on_status=self.on_state_send_status,
        )

        if args.dry_run:
            self.reader = FakeReader(args.cols, args.rows, args.dry_fps,
                                      self.on_frame, on_status=self.on_serial_status)
        else:
            header = bytes.fromhex(args.header.strip().replace(" ", ""))
            parser = FrameParser(args.cols, args.rows, header, args.pre, args.post, self.on_frame)
            self.reader = SerialReader(args.port, args.baud, parser, on_status=self.on_serial_status)

    def on_frame(self, ts, frame):
        pressure_vector = frame.reshape(-1)
        self.latest_frame.set(ts, pressure_vector)

        if not self.monitor.is_active():
            return

        calib, crit_p, crit_t = self.runtime_config.get()
        fired_idx, _risk_mask = self.risk_acc.update(pressure_vector, calib, crit_p, crit_t)
        if fired_idx.size == 0:
            return
        pressure_mask_idx = np.nonzero(
            pressure_vector > self.args.pressure_mask_threshold
        )[0]
        self.sender.enqueue({
            "accumulated_time": crit_t,
            "risky_idx": fired_idx.tolist(),
            "pressure_mask_idx": pressure_mask_idx.tolist(),
        })

    def on_command(self, command):
        if command == "state":
            ts, pressure_vector = self.latest_frame.get()
            self.state_sender.enqueue({
                "timestamp": ts,
                "pressure": pressure_vector.tolist() if pressure_vector is not None else [],
            })
            return
        try:
            new_state = self.monitor.apply(command)
        except ValueError as e:
            print(f"[monitor] {e}", flush=True)
            return
        print(f"[monitor] {command} -> {new_state}", flush=True)

    def on_serial_status(self, connected, msg):
        print(f"[serial] {msg}", flush=True)

    def on_poll_status(self, ok, msg):
        print(f"[config] {msg}", flush=True)

    def on_command_status(self, ok, msg):
        print(f"[command] {msg}", flush=True)

    def on_send_status(self, ok, msg):
        print(f"[event] {msg}", flush=True)

    def on_state_send_status(self, ok, msg):
        print(f"[state] {msg}", flush=True)

    def run(self):
        def handle_sig(signum, frame):
            self.stop_event.set()
        signal.signal(signal.SIGINT, handle_sig)
        signal.signal(signal.SIGTERM, handle_sig)

        self.reader.start()
        self.poller.start()
        self.command_poller.start()
        self.sender.start()
        self.state_sender.start()
        print("[client] running... press Ctrl+C to stop", flush=True)
        try:
            while not self.stop_event.is_set():
                self.stop_event.wait(0.5)
        finally:
            self.reader.stop()
            self.poller.stop()
            self.command_poller.stop()
            self.sender.stop()
            self.state_sender.stop()
            print("[client] stopped", flush=True)


def main(argv=None):
    args = build_parser().parse_args(argv)
    ClientApp(args).run()


if __name__ == "__main__":
    main()
