"""Headless CLI recorder.

Usage:
    python cmd/start.py [--port /dev/ttyUSB0] [--outpath my_log]
                        [--baud 921600] [--cols 32] [--rows 64]
                        [--header A55A] [--pre 6] [--post 2]
                        [--interval 1.0]
                        [--upload] [--upload-interval 600]
                        [--wandb-project NAME] [--wandb-entity NAME]
                        [--wandb-run-name NAME]
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

import numpy as np

from sensor import config
from sensor.csv_logger import CsvLogger
from sensor.frame_parser import FrameParser
from sensor.serial_reader import SerialReader


DEFAULT_PORT = "/dev/ttyUSB0"
DEFAULT_OUT_DIR = os.path.join(os.path.expanduser("~"), "sensor_logs")


def build_parser():
    p = argparse.ArgumentParser(prog="sensor.start", description="Sensor Recorder CLI")
    p.add_argument("--port", default=DEFAULT_PORT, help=f"Serial port (default: {DEFAULT_PORT})")
    p.add_argument("--baud", type=int, default=config.DEFAULT_BAUD)
    p.add_argument("--cols", type=int, default=config.DEFAULT_COLS)
    p.add_argument("--rows", type=int, default=config.DEFAULT_ROWS)
    p.add_argument("--header", default=config.DEFAULT_HEADER_HEX, help="hex string, e.g. A55A")
    p.add_argument("--pre", type=int, default=config.DEFAULT_PRE_SKIP)
    p.add_argument("--post", type=int, default=config.DEFAULT_POST_SKIP)
    p.add_argument("--interval", type=float, default=1.0,
                   help="save interval in seconds (default 1.0, 0 = every frame)")
    p.add_argument("--outpath", default=None,
                   help=f"output CSV path (default: {DEFAULT_OUT_DIR}/sensor_<timestamp>.csv)")
    p.add_argument("--upload", action="store_true",
                   help="stream metrics to wandb and upload CSV as artifact periodically")
    p.add_argument("--upload-interval", type=float, default=86400.0,
                   help="CSV upload period in seconds (default 86400 = 1 day). "
                        "After each upload, recording rotates to a new file "
                        "with a (2), (3), ... suffix.")
    p.add_argument("--wandb-project", default="sensor-recorder", help="wandb project name")
    p.add_argument("--wandb-entity", default=None, help="wandb entity (user/team)")
    p.add_argument("--wandb-run-name", default=None, help="wandb run name (default: auto)")
    p.add_argument("--dry-run", action="store_true",
                   help="generate synthetic frames instead of reading the serial port "
                        "(for testing CSV writes, wandb upload, and network resilience)")
    p.add_argument("--dry-fps", type=float, default=30.0,
                   help="synthetic frame rate in dry-run mode (default 30)")
    return p


class FakeReader:
    """Synthetic frame producer for --dry-run. Mimics SerialReader.start/stop."""

    def __init__(self, cols, rows, fps, on_frame, on_status=None):
        self.cols = cols
        self.rows = rows
        self.period = 1.0 / max(fps, 1e-3)
        self.on_frame = on_frame
        self.on_status = on_status or (lambda c, m: None)
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
        x = np.linspace(0, 4 * np.pi, self.cols, dtype=np.float32)
        y = np.linspace(0, 4 * np.pi, self.rows, dtype=np.float32)
        xx, yy = np.meshgrid(x, y)
        i = 0
        while not self._stop.is_set():
            wave = 127 + 100 * np.sin(xx + i * 0.1) * np.cos(yy + i * 0.05)
            frame = np.clip(wave, 0, 255).astype(np.uint8)
            try:
                self.on_frame(time.time(), frame)
            except Exception:
                pass
            i += 1
            if self._stop.wait(self.period):
                break
        self.on_status(False, "Dry-run: stopped")


def resolve_outpath(raw):
    if raw is None:
        fname = time.strftime("sensor_%Y%m%d_%H%M%S.csv")
        return os.path.join(DEFAULT_OUT_DIR, fname)
    path = os.path.expanduser(raw)
    root, ext = os.path.splitext(path)
    if not ext:
        path = root + ".csv"
    if not os.path.isabs(path):
        path = os.path.join(DEFAULT_OUT_DIR, path)
    return path


class WandbUploader:
    """Streams scalar metrics to wandb. The Recorder owns the CSV file;
    at each interval the Recorder rotates to a new file and hands the
    closed file path back for artifact upload.

    Resilient to network drops:
      - wandb.init is retried in the background until it succeeds
      - log() failures are swallowed (wandb has its own internal retry)
      - failed artifact uploads are queued and retried each interval
        (and once more at shutdown)
    """

    INIT_RETRY_S = 30.0

    def __init__(self, args, outpath, stop_event, recorder):
        try:
            import wandb  # noqa: F401
        except ImportError as e:
            raise RuntimeError("wandb not installed. Run: pip install wandb") from e
        import wandb
        self.wandb = wandb
        self.args = args
        self.base_name = os.path.splitext(os.path.basename(outpath))[0]
        self.interval = args.upload_interval
        self.stop_event = stop_event
        self.recorder = recorder
        self.run = None
        self._wandb_config = {
            "port": args.port,
            "baud": args.baud,
            "cols": args.cols,
            "rows": args.rows,
            "header": args.header,
            "pre": args.pre,
            "post": args.post,
            "save_interval": args.interval,
            "outpath": outpath,
        }
        self._pending = []  # list of (path, final_flag) waiting to upload
        self._pending_lock = threading.Lock()
        self._init_failures = 0
        self._log_failures = 0
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        # Attempt the first init synchronously so the user sees the run URL
        # immediately when network is up; if it fails we retry in the loop.
        self._try_init()
        self._thread.start()

    def _try_init(self):
        if self.run is not None:
            return True
        try:
            self.run = self.wandb.init(
                project=self.args.wandb_project,
                entity=self.args.wandb_entity,
                name=self.args.wandb_run_name,
                config=self._wandb_config,
                reinit=True,
            )
            print(f"[wandb] run: {self.run.url}", flush=True)
            self._init_failures = 0
            return True
        except Exception as e:
            self._init_failures += 1
            if self._init_failures <= 3 or self._init_failures % 10 == 0:
                print(f"[wandb] init failed (attempt {self._init_failures}): {e}. "
                      f"Will retry.", file=sys.stderr, flush=True)
            self.run = None
            return False

    def log_frame(self, ts, frame, saved_count):
        if self.run is None:
            return  # not connected yet; metric stream resumes after init succeeds
        try:
            self.wandb.log(
                {
                    "min": int(frame.min()),
                    "max": int(frame.max()),
                    "mean": float(frame.mean()),
                    "saved_count": saved_count,
                },
                step=saved_count,
            )
            self._log_failures = 0
        except Exception as e:
            self._log_failures += 1
            if self._log_failures <= 3 or self._log_failures % 50 == 0:
                print(f"[wandb] log failed (#{self._log_failures}): {e}",
                      file=sys.stderr, flush=True)

    def _enqueue(self, path, final):
        with self._pending_lock:
            self._pending.append((path, final))

    def _flush_pending(self):
        if self.run is None:
            return
        with self._pending_lock:
            queue = list(self._pending)
            self._pending.clear()
        leftover = []
        for path, final in queue:
            if not self._upload_once(path, final):
                leftover.append((path, final))
        if leftover:
            with self._pending_lock:
                # prepend so order is preserved on next attempt
                self._pending = leftover + self._pending

    def _upload_once(self, path, final):
        """Single attempt. Returns True on success, False on failure."""
        if not os.path.exists(path):
            print(f"[wandb] file missing, dropping: {path}", flush=True)
            return True  # don't keep retrying a missing file
        try:
            art = self.wandb.Artifact(
                name=self.base_name,
                type="sensor-log",
                metadata={
                    "final": final,
                    "uploaded_at": time.time(),
                    "source_file": os.path.basename(path),
                },
            )
            art.add_file(path)
            self.run.log_artifact(art)
            tag = "final" if final else "periodic"
            print(f"[wandb] uploaded artifact ({tag}) <- {path}", flush=True)
            return True
        except Exception as e:
            print(f"[wandb] upload failed for {path}: {e}. Will retry.",
                  file=sys.stderr, flush=True)
            return False

    def _upload_file(self, path, final=False):
        """Try to upload now; on failure, enqueue for retry."""
        if self.run is None or not self._upload_once(path, final):
            self._enqueue(path, final)

    def _loop(self):
        while not self.stop_event.is_set():
            # If init didn't succeed yet, retry on a short cycle.
            if self.run is None:
                if self.stop_event.wait(self.INIT_RETRY_S):
                    break
                self._try_init()
                continue

            if self.stop_event.wait(self.interval):
                break

            # Always try the pending queue first, in case prior intervals failed.
            self._flush_pending()

            closed_path = self.recorder.rotate()
            if closed_path is not None:
                self._upload_file(closed_path, final=False)

    def shutdown(self):
        try:
            # Attempt one last init if we never connected.
            if self.run is None:
                self._try_init()
            if self.run is not None:
                self._flush_pending()
            current = self.recorder.current_outpath
            if current is not None:
                self._upload_file(current, final=True)
            if self.run is not None:
                self._flush_pending()
            with self._pending_lock:
                if self._pending:
                    print(f"[wandb] {len(self._pending)} file(s) NOT uploaded "
                          f"due to network. They remain on disk:",
                          file=sys.stderr, flush=True)
                    for path, _ in self._pending:
                        print(f"  - {path}", file=sys.stderr, flush=True)
        finally:
            if self.run is not None:
                try:
                    self.run.finish()
                except Exception:
                    pass


class Recorder:
    def __init__(self, args):
        self.args = args
        self.logger = None
        self.last_save_ts = 0.0
        self.interval = args.interval
        self.stop_event = threading.Event()
        self.frame_count = 0
        self.saved_count = 0
        self.uploader = None
        self.base_outpath = None
        self.current_outpath = None
        self.rotation_idx = 1
        self.lock = threading.Lock()

    def _next_rotated_path(self):
        root, ext = os.path.splitext(self.base_outpath)
        idx = self.rotation_idx + 1
        while True:
            candidate = f"{root} ({idx}){ext}"
            if not os.path.exists(candidate):
                return candidate, idx
            idx += 1

    def rotate(self):
        """Close the current CSV, open the next rotated one, return the closed path."""
        with self.lock:
            if self.logger is None or self.current_outpath is None:
                return None
            closed = self.current_outpath
            self.logger.close()
            new_path, new_idx = self._next_rotated_path()
            self.rotation_idx = new_idx
            self.logger = CsvLogger(new_path, self.args.cols, self.args.rows)
            self.logger.open()
            self.current_outpath = new_path
            print(f"[rec] rotated -> {new_path}", flush=True)
            return closed

    def on_frame(self, ts, frame):
        self.frame_count += 1
        if self.interval <= 0 or (ts - self.last_save_ts) >= self.interval:
            self.last_save_ts = ts
            with self.lock:
                try:
                    self.logger.write(ts, frame)
                    self.saved_count += 1
                except Exception as e:
                    print(f"[write error] {e}", file=sys.stderr)
            fmin = int(frame.min())
            fmax = int(frame.max())
            fmean = float(frame.mean())
            print(
                f"[{time.strftime('%H:%M:%S', time.localtime(ts))}] "
                f"saved #{self.saved_count}  "
                f"min={fmin:3d}  max={fmax:3d}  mean={fmean:6.2f}  "
                f"(fps≈{self.frame_count})",
                flush=True,
            )
            self.frame_count = 0
            if self.uploader is not None:
                try:
                    self.uploader.log_frame(ts, frame, self.saved_count)
                except Exception as e:
                    print(f"[wandb] log failed: {e}", file=sys.stderr, flush=True)

    def on_status(self, connected, msg):
        print(f"[serial] {msg}", flush=True)

    def run(self):
        args = self.args
        if not args.dry_run:
            if args.port == DEFAULT_PORT and not os.path.exists(DEFAULT_PORT):
                raise FileNotFoundError(
                    f"{DEFAULT_PORT} not found. Plug in the device or pass --port."
                )
            if not os.path.exists(args.port):
                raise FileNotFoundError(f"Serial port not found: {args.port}")

        outpath = resolve_outpath(args.outpath)
        try:
            header = bytes.fromhex(args.header.strip().replace(" ", ""))
        except ValueError as e:
            raise ValueError(f"Invalid --header hex: {args.header}") from e
        if not header:
            raise ValueError("--header must not be empty")

        self.base_outpath = outpath
        self.current_outpath = outpath
        self.logger = CsvLogger(outpath, args.cols, args.rows)
        self.logger.open()
        print(f"[rec] writing to {outpath}", flush=True)
        print(
            f"[cfg] port={args.port} baud={args.baud} "
            f"cols={args.cols} rows={args.rows} "
            f"header={args.header} pre={args.pre} post={args.post} "
            f"interval={self.interval}s",
            flush=True,
        )

        if args.upload:
            self.uploader = WandbUploader(args, outpath, self.stop_event, self)
            self.uploader.start()

        if args.dry_run:
            print(f"[dry-run] generating synthetic frames at {args.dry_fps} fps", flush=True)
            reader = FakeReader(args.cols, args.rows, args.dry_fps,
                                self.on_frame, on_status=self.on_status)
        else:
            parser = FrameParser(args.cols, args.rows, header, args.pre, args.post, self.on_frame)
            reader = SerialReader(args.port, args.baud, parser, on_status=self.on_status)

        def handle_sig(signum, frame):
            self.stop_event.set()
        signal.signal(signal.SIGINT, handle_sig)
        signal.signal(signal.SIGTERM, handle_sig)

        reader.start()
        print("[rec] recording... press Ctrl+C to stop", flush=True)
        try:
            while not self.stop_event.is_set():
                self.stop_event.wait(0.5)
        finally:
            reader.stop()
            # Close the CSV first so all buffered rows are flushed to disk,
            # then let the uploader push the finalized file as the final artifact.
            with self.lock:
                if self.logger is not None:
                    self.logger.close()
                    self.logger = None
            if self.uploader is not None:
                self.uploader.shutdown()
            print(f"[rec] stopped. saved {self.saved_count} frames "
                  f"-> {self.current_outpath}", flush=True)


def main(argv=None):
    args = build_parser().parse_args(argv)
    Recorder(args).run()


if __name__ == "__main__":
    main()
