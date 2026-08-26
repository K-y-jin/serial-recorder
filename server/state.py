"""Thread-safe in-memory state for the real server: config thresholds,
pending monitor command, latest/history risk events, and the latest
reported pressure state. A single global mutation lock is enough at this
scale (mock_server/server.py uses the same pattern)."""
import threading
import time
from collections import deque

DEFAULT_CALIBRATION_FACTOR = 0.4755
DEFAULT_CRITICAL_PRESSURE = 32.0
DEFAULT_CRITICAL_TIME = 90.0
DEFAULT_COLS = 32
DEFAULT_ROWS = 64
EVENT_HISTORY_MAXLEN = 50


class ServerState:
    def __init__(self, cols=DEFAULT_COLS, rows=DEFAULT_ROWS,
                 calibration_factor=DEFAULT_CALIBRATION_FACTOR,
                 critical_pressure=DEFAULT_CRITICAL_PRESSURE,
                 critical_time=DEFAULT_CRITICAL_TIME, clock=time.time):
        self._lock = threading.Lock()
        self._clock = clock
        self.config = {
            "cols": cols,
            "rows": rows,
            "calibration_factor": calibration_factor,
            "critical_pressure": critical_pressure,
            "critical_time": critical_time,
            "mask_excluded_idx": [],  # flat cell indices excluded from detection; empty = whole grid detected
        }
        self.pending_command = None
        self.latest_event = None
        self.event_history = deque(maxlen=EVENT_HISTORY_MAXLEN)
        self.latest_state = None
        self.state_reports = []
        self.latest_image = None
        self.last_seen = None
        self.connected = None  # None = unknown (no contact yet)

    def get_config(self):
        with self._lock:
            return dict(self.config)

    def update_config(self, updates):
        with self._lock:
            self.config.update(updates)
            return dict(self.config)

    def set_command(self, command):
        with self._lock:
            self.pending_command = command

    def consume_command(self):
        with self._lock:
            cmd = self.pending_command
            self.pending_command = None
            return cmd

    def record_event(self, payload):
        record = dict(payload)
        record["received_at"] = self._clock()
        with self._lock:
            self.latest_event = record
            self.event_history.append(record)
        return record

    def clear_mock_latest_event(self):
        """Drops mock-tagged records from event_history, and un-sticks
        latest_event if it's currently showing a mock warning -- so the
        dashboard canvas stops rendering a mock event's risky cells after
        "모의 경고 삭제" instead of redrawing the same stale picture on
        every poll until the next real event arrives."""
        with self._lock:
            self.event_history = deque(
                (r for r in self.event_history if not r.get("is_mock")),
                maxlen=EVENT_HISTORY_MAXLEN,
            )
            if self.latest_event and self.latest_event.get("is_mock"):
                self.latest_event = self.event_history[-1] if self.event_history else None

    def record_state(self, payload):
        with self._lock:
            self.latest_state = dict(payload)
            self.state_reports.append(dict(payload))
        return self.latest_state

    def get_latest_state(self):
        with self._lock:
            return dict(self.latest_state) if self.latest_state else None

    def record_image(self, image_bytes):
        with self._lock:
            self.latest_image = image_bytes

    def get_latest_image(self):
        with self._lock:
            return self.latest_image

    def touch(self):
        """Records that the client just contacted the server (GET /config,
        GET /command, POST /event/state/image) -- the connection heartbeat."""
        with self._lock:
            self.last_seen = self._clock()

    def get_last_seen(self):
        with self._lock:
            return self.last_seen

    def set_connected(self, connected):
        """Updates the connected flag; returns True iff this is a real
        transition (not the first-ever observation), so callers can alert
        exactly once per disconnect instead of on every check."""
        with self._lock:
            changed = self.connected is not None and self.connected != connected
            self.connected = connected
            return changed

    def is_connected(self):
        with self._lock:
            return self.connected

    def snapshot(self):
        """Everything the dashboard's /api/latest needs, in one locked read."""
        with self._lock:
            return {
                "cols": self.config["cols"],
                "rows": self.config["rows"],
                "mask_excluded_idx": list(self.config["mask_excluded_idx"]),
                "latest_event": dict(self.latest_event) if self.latest_event else None,
                "latest_state": dict(self.latest_state) if self.latest_state else None,
                "has_image": self.latest_image is not None,
                "connected": self.connected,
                "last_seen": self.last_seen,
            }
