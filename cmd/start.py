"""Headless CLI recorder.

Usage:
    python cmd/start.py [--port /dev/ttyUSB0] [--outpath my_log]
                        [--baud 921600] [--cols 32] [--rows 64]
                        [--header A55A] [--pre 6] [--post 2]
                        [--interval 1.0]
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
DEFAULT_OUT_DIR = os.path.join(os.path.expanduser("~"), "bliss_logs")


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


class Recorder:
    def __init__(self, args):
        self.args = args
        self.logger = None
        self.last_save_ts = 0.0
        self.interval = args.interval
        self.stop_event = threading.Event()
        self.frame_count = 0
        self.saved_count = 0

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
            print(f"[rec] stopped. saved {self.saved_count} frames -> {outpath}", flush=True)


def main(argv=None):
    args = build_parser().parse_args(argv)
    Recorder(args).run()


if __name__ == "__main__":
    main()
