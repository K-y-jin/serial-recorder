"""Persists received risk warnings to disk: one JSON-line per warning in
warnings.log, plus the snapshot PNG (if/when POST /image arrives) saved
under images/. Kept separate from ServerState (which only holds the
latest-for-dashboard values in memory) so a restart doesn't lose history."""
import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


def _default_dir():
    """%APPDATA%\\carerobot\\press_warnings on Windows (the conventional
    per-user app-data location, always writable and independent of where
    the exe happens to be run from); a repo-relative fallback elsewhere
    (dev machines / CI don't set APPDATA)."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return str(Path(appdata) / "carerobot" / "press_warnings")
    return "nrc/press_warnings"


DEFAULT_DIR = _default_dir()
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

    def read_history(self, limit=50):
        """Returns the most recent `limit` logged warnings (POST /event
        records), newest first, for the dashboard's history list."""
        if not self.log_path.exists():
            return []
        with self._lock:
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        records = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                logger.warning("skipping malformed warnings.log line")
        records.reverse()
        return records

    def annotate_site(self, received_at, site):
        """Attaches a user-entered '위험 발생 부위' (body site) to the
        warning record matching `received_at`, rewriting warnings.log in
        place. Returns True if a matching record was found and updated."""
        with self._lock:
            if not self.log_path.exists():
                return False
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            found = False
            new_lines = []
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    new_lines.append(line)
                    continue
                try:
                    record = json.loads(stripped)
                except ValueError:
                    new_lines.append(line)
                    continue
                if not found and record.get("received_at") == received_at:
                    record["site"] = site
                    found = True
                    new_lines.append(json.dumps(record, ensure_ascii=False) + "\n")
                else:
                    new_lines.append(line)
            if found:
                with open(self.log_path, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
        return found

    def clear_mock_events(self):
        """Removes all mock-warning records (is_mock=True) from
        warnings.log, keeping real client warnings intact. Returns the
        number of records removed."""
        with self._lock:
            if not self.log_path.exists():
                return 0
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            kept_lines = []
            removed = 0
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    kept_lines.append(line)
                    continue
                try:
                    record = json.loads(stripped)
                except ValueError:
                    kept_lines.append(line)
                    continue
                if record.get("is_mock"):
                    removed += 1
                else:
                    kept_lines.append(line)
            if removed:
                with open(self.log_path, "w", encoding="utf-8") as f:
                    f.writelines(kept_lines)
        return removed

    def save_image(self, image_bytes, received_at):
        """Saves a warning snapshot PNG (POST /image), named by its
        received timestamp so it can be matched up with warnings.log."""
        filename = f"{received_at:.6f}.png"
        path = self.image_dir / filename
        with open(path, "wb") as f:
            f.write(image_bytes)
        logger.info("warning image saved -> %s", path)
        return str(path)
