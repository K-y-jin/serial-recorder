"""Client-side persistence, independent of whether the server is
reachable:

- warnings.log: one JSON line per risk warning as soon as it fires
  (before any network attempt), so nothing is lost if the send later
  fails or the server is unreachable
- images/: a local copy of every risk-warning snapshot PNG that gets
  sent to the server
- send.log: one JSON line per send attempt (event/state/image), success
  or failure
"""
import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DIR = "logs/client_warnings"
WARNING_LOG_FILENAME = "warnings.log"
SEND_LOG_FILENAME = "send.log"
IMAGE_DIRNAME = "images"


class WarningLog:
    def __init__(self, base_dir=DEFAULT_DIR, clock=time.time):
        self.base_dir = Path(base_dir)
        self.image_dir = self.base_dir / IMAGE_DIRNAME
        self.warning_log_path = self.base_dir / WARNING_LOG_FILENAME
        self.send_log_path = self.base_dir / SEND_LOG_FILENAME
        self._clock = clock
        self._lock = threading.Lock()
        self.image_dir.mkdir(parents=True, exist_ok=True)

    def log_warning(self, payload):
        """Records a risk warning (the same payload POSTed to /event)."""
        record = dict(payload)
        record["logged_at"] = self._clock()
        self._append(self.warning_log_path, record)
        logger.info("warning logged -> %s", self.warning_log_path)

    def save_image(self, image_bytes, ts=None):
        """Saves a local copy of a risk-warning snapshot PNG, named by
        the frame timestamp it was rendered from."""
        ts = self._clock() if ts is None else ts
        path = self.image_dir / f"{ts:.6f}.png"
        with open(path, "wb") as f:
            f.write(image_bytes)
        logger.info("warning image saved -> %s", path)
        return str(path)

    def log_send(self, kind, ok, message):
        """Records the outcome of one send attempt: kind is "event",
        "state", or "image"; ok is whether it ultimately succeeded."""
        record = {
            "kind": kind,
            "ok": ok,
            "message": message,
            "logged_at": self._clock(),
        }
        self._append(self.send_log_path, record)

    def _append(self, path, record):
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
