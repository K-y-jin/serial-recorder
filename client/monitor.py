"""Server-driven monitor state machine: start / pause / stop / reset / state.

The serial reader keeps running regardless of monitor state (so the latest
pressure frame is always available for a `state` query); only risk
accumulation is gated by `is_active()`.
"""
import threading

RUNNING = "running"
PAUSED = "paused"
STOPPED = "stopped"

_VALID_COMMANDS = {"start", "pause", "stop", "reset", "state"}


class UnknownCommandError(ValueError):
    pass


class MonitorState:
    def __init__(self, risk_acc, initial_state=RUNNING):
        self.risk_acc = risk_acc
        self._lock = threading.Lock()
        self._state = initial_state

    @property
    def state(self):
        with self._lock:
            return self._state

    def is_active(self):
        with self._lock:
            return self._state == RUNNING

    def apply(self, command):
        """Apply a command from the server. Returns the resulting state
        string, or None for `state` (which doesn't change monitor state)."""
        if command not in _VALID_COMMANDS:
            raise UnknownCommandError(f"unknown command: {command!r}")

        with self._lock:
            if command == "start":
                self._state = RUNNING
                self.risk_acc.resync()
            elif command == "pause":
                self._state = PAUSED
            elif command == "stop":
                self._state = STOPPED
            elif command == "reset":
                # reset = pause + reset(accumulated_risk=0) + start
                self.risk_acc.reset()
                self.risk_acc.resync()
                self._state = RUNNING
            elif command == "state":
                return None
            return self._state
