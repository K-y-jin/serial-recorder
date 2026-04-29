"""Tests that exercise the recorder without a real serial device.

Covers:
  - dry-run subprocess actually writes a CSV
  - Recorder.rotate() creates suffixed files
  - WandbUploader queues failed uploads and retries (network drop simulation)
  - WandbUploader retries init() when offline at startup

Run with:
    python -m pytest tests/test_dry_run.py -v
"""
import csv
import importlib.util
import os
import subprocess
import sys
import threading
import time

import pytest  # noqa: F401  -- pytest collected as runner

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# `cmd` is a folder of scripts, not a Python package — load start.py by path.
_spec = importlib.util.spec_from_file_location(
    "cmd_start", os.path.join(ROOT, "cmd", "start.py")
)
_start_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_start_mod)
Recorder = _start_mod.Recorder
WandbUploader = _start_mod.WandbUploader
build_parser = _start_mod.build_parser


# ----------------------------- helpers -----------------------------

class FakeWandb:
    """Minimal stand-in for the wandb module. Configurable failure modes."""

    class _Run:
        def __init__(self):
            self.url = "fake://run"
            self.logged = []
            self.artifacts = []
            self.finished = False

        def log_artifact(self, art):
            if getattr(art, "_should_fail", False):
                raise RuntimeError("simulated artifact upload failure")
            self.artifacts.append(art)

        def finish(self):
            self.finished = True

    class Artifact:
        def __init__(self, name, type, metadata=None):
            self.name = name
            self.type = type
            self.metadata = metadata or {}
            self.files = []
            self._should_fail = False

        def add_file(self, path):
            self.files.append(path)

    def __init__(self, init_fails=0, log_artifact_fails=0):
        self._init_fails_remaining = init_fails
        self._log_artifact_fails_remaining = log_artifact_fails
        self.run = None
        self.log_calls = []

    def init(self, **kwargs):
        if self._init_fails_remaining > 0:
            self._init_fails_remaining -= 1
            raise RuntimeError("simulated wandb.init failure (offline)")
        self.run = FakeWandb._Run()
        return self.run

    def log(self, payload, step=None):
        self.log_calls.append((payload, step))


def make_args(tmp_path, **overrides):
    p = build_parser()
    args = p.parse_args(["--dry-run"])
    args.outpath = str(tmp_path / "test_log")  # will become test_log.csv
    args.dry_fps = 30.0
    args.interval = 0.1
    for k, v in overrides.items():
        setattr(args, k, v)
    return args


# ----------------------------- subprocess tests -----------------------------

def test_dry_run_writes_csv(tmp_path):
    """End-to-end: spawn the CLI in dry-run mode, kill it, verify CSV content."""
    out = tmp_path / "drytest.csv"
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "cmd", "start.py"),
         "--dry-run", "--outpath", str(out),
         "--interval", "0.05", "--dry-fps", "60"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        time.sleep(2.0)
    finally:
        proc.send_signal(subprocess.signal.SIGINT)
        proc.wait(timeout=10)

    assert out.exists(), f"CSV was not created at {out}"
    with open(out) as fh:
        reader = csv.reader(fh)
        rows = list(reader)
    assert rows[0][0] == "timestamp"
    assert len(rows) > 5, f"Too few rows: {len(rows)}"
    # Each data row should have timestamp + cols*rows values
    expected_cols = 1 + 32 * 64
    assert len(rows[1]) == expected_cols


# ----------------------------- unit tests -----------------------------

def test_rotation_creates_suffixed_files(tmp_path):
    """Recorder.rotate() should close current and open '<base> (N).csv'."""
    args = make_args(tmp_path, upload=False)
    rec = Recorder(args)

    # Bootstrap: open the first file manually (mirroring run() init).
    from sensor.csv_logger import CsvLogger
    base = str(tmp_path / "rot_test.csv")
    rec.base_outpath = base
    rec.current_outpath = base
    rec.logger = CsvLogger(base, args.cols, args.rows)
    rec.logger.open()

    closed1 = rec.rotate()
    assert closed1 == base
    assert rec.current_outpath == str(tmp_path / "rot_test (2).csv")
    assert os.path.exists(rec.current_outpath)

    closed2 = rec.rotate()
    assert closed2 == str(tmp_path / "rot_test (2).csv")
    assert rec.current_outpath == str(tmp_path / "rot_test (3).csv")

    rec.logger.close()


def test_rotation_skips_existing_files(tmp_path):
    """If '<base> (2).csv' already exists, rotation should skip to (3)."""
    base = tmp_path / "skip.csv"
    base.write_text("preexisting")
    (tmp_path / "skip (2).csv").write_text("also preexisting")

    args = make_args(tmp_path, upload=False)
    rec = Recorder(args)
    from sensor.csv_logger import CsvLogger
    rec.base_outpath = str(base)
    rec.current_outpath = str(base)
    rec.logger = CsvLogger(str(base), args.cols, args.rows)
    rec.logger.open()

    rec.rotate()
    assert rec.current_outpath == str(tmp_path / "skip (3).csv")
    rec.logger.close()


# ------------------------- wandb resilience tests -------------------------

def _make_uploader(tmp_path, fake_wandb, recorder, **arg_overrides):
    """Construct a WandbUploader with the wandb module replaced."""
    args = make_args(tmp_path, upload=True, upload_interval=0.5, **arg_overrides)
    outpath = str(tmp_path / "wbtest.csv")
    # Pre-create the file so artifact.add_file() doesn't fail.
    open(outpath, "w").close()

    stop_event = threading.Event()
    # Build uploader without doing real wandb init
    class _Stub(WandbUploader):
        def __init__(self_):
            self_.wandb = fake_wandb
            self_.args = args
            self_.base_name = "wbtest"
            self_.interval = args.upload_interval
            self_.stop_event = stop_event
            self_.recorder = recorder
            self_.run = None
            self_._wandb_config = {}
            self_._pending = []
            self_._pending_lock = threading.Lock()
            self_._init_failures = 0
            self_._log_failures = 0
            self_._thread = None

    up = _Stub()
    return up, outpath, stop_event


class _DummyRecorder:
    def __init__(self, current_outpath):
        self.current_outpath = current_outpath

    def rotate(self):
        return self.current_outpath


def test_init_retries_when_offline_at_startup(tmp_path):
    """If wandb.init fails twice then succeeds, uploader recovers."""
    fake = FakeWandb(init_fails=2)
    rec = _DummyRecorder(str(tmp_path / "f.csv"))
    open(rec.current_outpath, "w").close()
    up, _, _ = _make_uploader(tmp_path, fake, rec)

    assert up._try_init() is False
    assert up._try_init() is False
    assert up._try_init() is True
    assert up.run is not None


def test_pending_queue_grows_on_upload_failure_then_drains(tmp_path):
    """Network drops → uploads queue. Network back → queue drains."""
    fake = FakeWandb(init_fails=0)
    rec = _DummyRecorder(str(tmp_path / "primary.csv"))
    open(rec.current_outpath, "w").close()
    up, _, _ = _make_uploader(tmp_path, fake, rec)
    up._try_init()
    assert up.run is not None

    # Simulate failures by making log_artifact raise.
    fail_flag = {"on": True}
    real_log = up.run.log_artifact

    def maybe_fail(art):
        if fail_flag["on"]:
            raise RuntimeError("net down")
        real_log(art)
    up.run.log_artifact = maybe_fail

    # Three failed uploads → all queued
    for i in range(3):
        path = str(tmp_path / f"q{i}.csv")
        open(path, "w").close()
        up._upload_file(path, final=False)
    assert len(up._pending) == 3

    # Network restored → flush should drain the queue
    fail_flag["on"] = False
    up._flush_pending()
    assert len(up._pending) == 0
    assert len(up.run.artifacts) == 3


def test_log_failure_is_swallowed(tmp_path):
    """A wandb.log exception must not propagate out of log_frame."""
    import numpy as np

    fake = FakeWandb(init_fails=0)
    rec = _DummyRecorder(str(tmp_path / "f.csv"))
    open(rec.current_outpath, "w").close()
    up, _, _ = _make_uploader(tmp_path, fake, rec)
    up._try_init()

    def boom(*a, **kw):
        raise RuntimeError("net down")
    fake.log = boom  # type: ignore[attr-defined]

    # Should not raise
    up.log_frame(time.time(), np.zeros((4, 4), dtype=np.uint8), saved_count=1)


def test_shutdown_reports_undelivered_files(tmp_path, capsys):
    """If files are still pending at shutdown, their paths are printed."""
    fake = FakeWandb(init_fails=0)
    rec = _DummyRecorder(str(tmp_path / "current.csv"))
    open(rec.current_outpath, "w").close()
    up, _, _ = _make_uploader(tmp_path, fake, rec)
    up._try_init()

    # Force every upload attempt to fail (including final)
    def always_fail(art):
        raise RuntimeError("net never came back")
    up.run.log_artifact = always_fail

    leftover = str(tmp_path / "leftover.csv")
    open(leftover, "w").close()
    up._enqueue(leftover, final=False)

    up.shutdown()
    captured = capsys.readouterr()
    assert "NOT uploaded" in captured.err
    assert leftover in captured.err
