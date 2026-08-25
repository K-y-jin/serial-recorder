"""Persists received risk warnings to disk: one JSON-line per warning in
warnings.log, plus the snapshot PNG (if/when POST /image arrives) saved
under images/. Kept separate from ServerState (which only holds the
latest-for-dashboard values in memory) so a restart doesn't lose history."""
import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DIR = "warnings"
LOG_FILENAME = "warnings.log"
IMAGE_DIRNAME = "images"


class WarningStore:
    def __init__(self, base_dir=DEFAULT_DIR):
        self.base_dir = Path(base_dir)
        self.image_dir = self.base_dir / IMAGE_DIRNAME
        self.log_path = self.base_dir / LOG_FILENAME
        self._lock = threading.Lock()
        self.image_dir.mkdir(parents=True, exist_ok=True)

    def log_event(self, payload, received_at):
        """Appends one JSON line for a client risk warning (POST /event)."""
        record = dict(payload)
        record["received_at"] = received_at
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        logger.info("warning logged -> %s", self.log_path)
        return record

    def save_image(self, image_bytes, received_at):
        """Saves a warning snapshot PNG (POST /image), named by its
        received timestamp so it can be matched up with warnings.log."""
        filename = f"{received_at:.6f}.png"
        path = self.image_dir / filename
        with open(path, "wb") as f:
            f.write(image_bytes)
        logger.info("warning image saved -> %s", path)
        return str(path)
