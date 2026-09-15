"""Persists dashboard-assigned display names for client_ids, so an admin
can rename a client (e.g. "pi-a" -> "301호") without touching the client
device itself. Stored as a single {client_id: display_name} JSON map at
the top of --warning-dir, independent of any one client's own
<warning_dir>/<client_id>/ subdirectory (see ConfigStore/WarningStore)."""
import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

FILENAME = "client_names.json"


class ClientNameStore:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.path = self.base_dir / FILENAME
        self._lock = threading.Lock()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._names = self._load()

    def _load(self):
        if not self.path.exists():
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("failed to load %s, ignoring: %s", self.path, e)
            return {}

    def _save(self):
        tmp_path = self.path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._names, f, ensure_ascii=False, indent=2)
        tmp_path.replace(self.path)

    def get(self, client_id):
        """Returns the display name for client_id, or None if never set."""
        with self._lock:
            return self._names.get(client_id)

    def all(self):
        with self._lock:
            return dict(self._names)

    def set(self, client_id, name):
        """name="" (or whitespace-only) clears back to the raw client_id."""
        name = name.strip()
        with self._lock:
            if name:
                self._names[client_id] = name
            else:
                self._names.pop(client_id, None)
            self._save()
        logger.info("client %s: display name -> %r", client_id, name or None)
        return name or None
