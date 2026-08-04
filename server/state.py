"""Thread-safe in-memory state for the real server: config thresholds,
pending monitor command, latest/history risk events, and the latest
reported pressure state. A single global mutation lock is enough at this
scale (mock_server/server.py uses the same pattern)."""
import threading
import time
from collections import deque

DEFAULT_CALIBRATION_FACTOR = 0.5
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
        }
        self.pending_command = None
        self.latest_event = None
        self.event_history = deque(maxlen=EVENT_HISTORY_MAXLEN)
        self.latest_state = None
        self.state_reports = []

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

    def record_state(self, payload):
        with self._lock:
            self.latest_state = dict(payload)
            self.state_reports.append(dict(payload))
        return self.latest_state

    def snapshot(self):
        """Everything the dashboard's /api/latest needs, in one locked read."""
        with self._lock:
            return {
                "cols": self.config["cols"],
                "rows": self.config["rows"],
                "latest_event": dict(self.latest_event) if self.latest_event else None,
                "latest_state": dict(self.latest_state) if self.latest_state else None,
            }
