"""Headless CLI recorder.

Usage:
    python cmd/start.py [--port /dev/ttyUSB0] [--outpath my_log]
                        [--baud 921600] [--cols 32] [--rows 64]
                        [--header A55A] [--pre 6] [--post 2]
                        [--interval 1.0]
                        [--upload] [--upload-interval 600]
                        [--wandb-project NAME] [--wandb-entity NAME]
                        [--wandb-run-name NAME]
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

from bliss import config
from bliss.csv_logger import CsvLogger
from bliss.frame_parser import FrameParser
from bliss.serial_reader import SerialReader


DEFAULT_PORT = "/dev/ttyUSB0"
DEFAULT_OUT_DIR = os.path.join(_PROJECT_ROOT, "bliss_logs")


def build_parser():
    p = argparse.ArgumentParser(prog="bliss.start", description="Bliss Recorder CLI")
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
                   help=f"output CSV path (default: {DEFAULT_OUT_DIR}/bliss_<timestamp>.csv)")
    p.add_argument("--upload", action="store_true",
                   help="stream metrics to wandb and upload CSV as artifact periodically")
    p.add_argument("--upload-interval", type=float, default=600.0,
                   help="CSV artifact upload period in seconds (default 600 = 10 min)")
    p.add_argument("--wandb-project", default="bliss-recorder", help="wandb project name")
    p.add_argument("--wandb-entity", default=None, help="wandb entity (user/team)")
    p.add_argument("--wandb-run-name", default=None, help="wandb run name (default: auto)")
    return p


def resolve_outpath(raw):
    if raw is None:
        fname = time.strftime("bliss_%Y%m%d_%H%M%S.csv")
        return os.path.join(DEFAULT_OUT_DIR, fname)
    path = os.path.expanduser(raw)
    root, ext = os.path.splitext(path)
    if not ext:
        path = root + ".csv"
    if not os.path.isabs(path):
        path = os.path.join(DEFAULT_OUT_DIR, path)
    return path


class WandbUploader:
    """Streams scalar metrics to wandb and uploads the CSV file as an artifact
    every `interval` seconds (and once at shutdown)."""

    def __init__(self, args, outpath, stop_event):
        try:
            import wandb  # noqa: F401
        except ImportError as e:
            raise RuntimeError("wandb not installed. Run: pip install wandb") from e
        import wandb
        self.wandb = wandb
        self.outpath = outpath
        self.artifact_name = os.path.splitext(os.path.basename(outpath))[0]
        self.interval = args.upload_interval
        self.stop_event = stop_event
        self.run = wandb.init(
            project=args.wandb_project,
            entity=args.wandb_entity,
            name=args.wandb_run_name,
            config={
                "port": args.port,
                "baud": args.baud,
                "cols": args.cols,
                "rows": args.rows,
                "header": args.header,
                "pre": args.pre,
                "post": args.post,
                "save_interval": args.interval,
                "outpath": outpath,
            },
            reinit=True,
        )
        print(f"[wandb] run: {self.run.url}", flush=True)
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._thread.start()

    def log_frame(self, ts, frame, saved_count):
        self.wandb.log(
            {
                "min": int(frame.min()),
                "max": int(frame.max()),
                "mean": float(frame.mean()),
                "saved_count": saved_count,
            },
            step=saved_count,
        )

    def _upload_artifact(self, final=False):
        if not os.path.exists(self.outpath):
            print("[wandb] file missing, skipping upload", flush=True)
            return
        try:
            art = self.wandb.Artifact(
                name=self.artifact_name,
                type="sensor-log",
                metadata={"final": final, "uploaded_at": time.time()},
            )
            art.add_file(self.outpath)
            self.run.log_artifact(art)
            tag = "final" if final else "periodic"
            print(f"[wandb] uploaded artifact ({tag}) <- {self.outpath}", flush=True)
        except Exception as e:
            print(f"[wandb] upload failed: {e}", file=sys.stderr, flush=True)

    def _loop(self):
        while not self.stop_event.is_set():
            if self.stop_event.wait(self.interval):
                break
            self._upload_artifact(final=False)

    def shutdown(self):
        try:
            self._upload_artifact(final=True)
        finally:
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

    def on_frame(self, ts, frame):
        self.frame_count += 1
        if self.interval <= 0 or (ts - self.last_save_ts) >= self.interval:
            self.last_save_ts = ts
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
            self.uploader = WandbUploader(args, outpath, self.stop_event)
            self.uploader.start()

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
            self.logger.close()
            if self.uploader is not None:
                self.uploader.shutdown()
            print(f"[rec] stopped. saved {self.saved_count} frames -> {outpath}", flush=True)


def main(argv=None):
    args = build_parser().parse_args(argv)
    Recorder(args).run()


if __name__ == "__main__":
    main()
