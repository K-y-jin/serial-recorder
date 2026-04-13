import csv
from datetime import datetime


class CsvLogger:
    def __init__(self, path, cols, rows):
        self.path = path
        self.cols = cols
        self.rows = rows
        self._fh = None
        self._writer = None
        self._count = 0

    def open(self):
        self._fh = open(self.path, "w", newline="")
        self._writer = csv.writer(self._fh)
        header = ["timestamp"] + [f"c{i}" for i in range(self.cols * self.rows)]
        self._writer.writerow(header)
        self._fh.flush()
        self._count = 0

    def write(self, timestamp, frame):
        if self._writer is None:
            return
        ts = datetime.fromtimestamp(timestamp).isoformat(timespec="milliseconds")
        row = [ts]
        row.extend(int(v) for v in frame.flatten())
        self._writer.writerow(row)
        self._count += 1
        if self._count % 30 == 0:
            self._fh.flush()

    def close(self):
        if self._fh is not None:
            try:
                self._fh.flush()
                self._fh.close()
            except Exception:
                pass
        self._fh = None
        self._writer = None
