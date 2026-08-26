"""Watches how recently the client last contacted the server (see
ServerState.touch(), called from GET /config, GET /command, and
POST /event|/state|/image) and declares it disconnected once too much
time passes without contact. Fires an alert exactly once per disconnect
transition -- not on every check -- and again once the client comes
back."""
import logging
import threading
import time

from server.alert import fire_alert

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 10.0
DEFAULT_CHECK_INTERVAL_S = 2.0


class ConnectionMonitor:
    def __init__(self, state, timeout_s=DEFAULT_TIMEOUT_S,
                 check_interval_s=DEFAULT_CHECK_INTERVAL_S, clock=time.time):
        self.state = state
        self.timeout_s = timeout_s
        self.check_interval_s = check_interval_s
        self._clock = clock
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

    def check_once(self):
        last_seen = self.state.get_last_seen()
        if last_seen is None:
            return  # client has never contacted us -- nothing to judge yet
        connected = (self._clock() - last_seen) <= self.timeout_s
        was_connected = self.state.is_connected()
        changed = self.state.set_connected(connected)
        if was_connected is None:
            # First-ever observation: worth logging (client connect time),
            # but not alert-worthy -- there was no prior state to alert
            # about a change from.
            logger.info("client %s (first contact)", "connected" if connected else "not connected")
            return
        if changed:
            if connected:
                logger.info("client connection restored")
                fire_alert("클라이언트 연결이 복구되었습니다.")
            else:
                logger.warning("client connection lost (no contact for >%.0fs)", self.timeout_s)
                fire_alert("클라이언트 연결이 끊어졌습니다.")

    def _run(self):
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception:
                logger.exception("connection check failed")
            if self._stop.wait(self.check_interval_s):
                break
