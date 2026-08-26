r"""Real server for the pressure risk monitoring client.

Implements the same REST contract as client/mock_server/server.py (GET/PUT
/config, POST /event, GET/PUT /command, POST /state) plus a dashboard that
visualizes the latest risk warning: pressure_mask_idx (cells under body
pressure -- the mattress "silhouette") shaded as background, risky_idx
(cells that exceeded critical_time) highlighted on top.

Every risk warning is persisted to disk (see server/warning_store.py):
each POST /event appends a JSON line to <warning-dir>/warnings.log, and
each POST /image saves the snapshot PNG under <warning-dir>/images/.

Client connection status is tracked from how recently the client last
contacted the server (GET /config, GET /command, POST /event|/state|
/image) -- see server/connection_monitor.py. If the client goes quiet
for longer than --client-timeout, it's marked disconnected (shown on the
dashboard) and an alert fires.

Endpoints:
  GET  /config      -> {"cols", "rows", "calibration_factor", "critical_pressure",
                        "critical_time", "mask_excluded_idx"}
  PUT  /config      -> update thresholds/grid size/mask, returns the new config.
                        mask_excluded_idx is a list of flat cell indices excluded
                        from risk detection on the client (empty = whole grid
                        detected).
  POST /event       -> client risk warning: {"accumulated_time", "risky_idx", "pressure_mask_idx"}
  GET  /command     -> {"command": "start"|"pause"|"stop"|"reset"|"state"|null}, consumed once
  PUT  /command     -> queue a pending command: {"command": "..."}
  POST /state       -> client's answer to a "state" command: {"timestamp", "pressure"}
  POST /image       -> risk-warning snapshot PNG (multipart field "image"): current
                        frame + risky-cell overlay, not accumulated
  GET  /image/latest -> the most recently received warning snapshot PNG
  GET  /dashboard   -> HTML dashboard
  GET  /api/latest  -> JSON snapshot for the dashboard poller, including
                        "connected"/"last_seen" client connection status
  GET  /api/meta    -> {"warning_dir"}, read-only server-side info for the dashboard
  GET  /api/defaults -> hardcoded default config values, for the dashboard's
                        "기본값으로 초기화" (reset to defaults) button
  GET  /api/config/pending -> {"pending", "config"}: a config restored from disk
                        on startup that's awaiting dashboard confirmation before
                        it takes effect (see create_app's startup restore logic)
  POST /api/config/pending/resolve -> {"action": "restore"|"default"}: applies
                        the pending config (or the hardcoded defaults) and
                        clears the pending state

Usage:
    python -m server.app [--host 0.0.0.0] [--port 5000]
                          [--cols 32] [--rows 64]
                          [--warning-dir %APPDATA%\carerobot\press_warnings]
                          [--client-timeout 10.0]
"""
import argparse
import io
import json
import logging
import sys
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from server.alert import fire_alert
from server.config_store import ConfigStore
from server.connection_monitor import DEFAULT_TIMEOUT_S as DEFAULT_CLIENT_TIMEOUT_S
from server.connection_monitor import ConnectionMonitor
from server.grid import idx_to_rowcol
from server.state import (
    DEFAULT_CALIBRATION_FACTOR,
    DEFAULT_COLS,
    DEFAULT_CRITICAL_PRESSURE,
    DEFAULT_CRITICAL_TIME,
    DEFAULT_ROWS,
    ServerState,
)
from server.warning_store import DEFAULT_DIR as DEFAULT_WARNING_DIR
from server.warning_store import WarningStore


MOCK_WARNING_DATA_PATH = Path(__file__).resolve().parent / "mock_warning_data.json"


def _load_mock_warning_data():
    with open(MOCK_WARNING_DATA_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _template_folder():
    """Resolve the templates/ dir both when run normally and when frozen
    into a PyInstaller exe, where files live under sys._MEIPASS instead
    of next to this source file."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    if hasattr(sys, "_MEIPASS"):
        return str(base / "server" / "templates")
    return str(base / "templates")


def create_app(state=None, warning_dir=DEFAULT_WARNING_DIR,
                client_timeout_s=DEFAULT_CLIENT_TIMEOUT_S):
    app = Flask(__name__, template_folder=_template_folder())
    app.logger.setLevel(logging.INFO)
    state = state or ServerState()
    warning_store = WarningStore(warning_dir)
    config_store = ConfigStore(warning_dir)
    connection_monitor = ConnectionMonitor(state, timeout_s=client_timeout_s)
    connection_monitor.start()

    def _apply_config(updates, reason, persist=True):
        snapshot = state.update_config(updates)
        app.logger.info("config %s -> %s", reason, snapshot)
        if persist:
            config_store.save(snapshot)
        return snapshot

    # A config saved from a previous run sits here, awaiting a decision
    # from the dashboard, instead of being applied automatically -- the
    # user may have wanted a fresh start rather than picking back up where
    # an unexpectedly-terminated server left off. Until resolved, state
    # stays on the ServerState defaults, and the client (which polls
    # GET /config immediately on its own startup/reconnect) sees defaults.
    _pending_lock = threading.Lock()
    _pending_restore = {"config": None}
    saved_config = config_store.load()
    if saved_config is not None:
        _pending_restore["config"] = saved_config
        app.logger.info(
            "config restore pending dashboard confirmation -> %s", saved_config
        )
    else:
        _apply_config(state.get_config(), "initialized")

    @app.get("/api/config/pending")
    def get_pending_config():
        with _pending_lock:
            cfg = _pending_restore["config"]
        return jsonify({"pending": cfg is not None, "config": cfg})

    @app.post("/api/config/pending/resolve")
    def resolve_pending_config():
        body = request.get_json(force=True)
        action = body.get("action")
        with _pending_lock:
            cfg = _pending_restore["config"]
            if cfg is None:
                return jsonify({"status": "error", "message": "no pending config"}), 400
            if action == "restore":
                snapshot = _apply_config(cfg, "restored (confirmed)")
            elif action == "default":
                snapshot = _apply_config(
                    state.get_config(), "initialized (user chose default)", persist=False
                )
                config_store.delete()
            else:
                return jsonify({"status": "error", "message": "invalid action"}), 400
            _pending_restore["config"] = None
        return jsonify(snapshot)

    @app.get("/config")
    def get_config():
        state.touch()
        return jsonify(state.get_config())

    @app.put("/config")
    def put_config():
        body = request.get_json(force=True)
        snapshot = _apply_config(body, "updated")
        return jsonify(snapshot)

    def _handle_event(data, log_prefix="EVENT"):
        record = state.record_event(data)
        app.logger.info(
            "%s accumulated_time=%s risky_idx=%s pressure_mask_idx=%d cells",
            log_prefix,
            data.get("accumulated_time"),
            data.get("risky_idx"),
            len(data.get("pressure_mask_idx", [])),
        )
        risky_idx = data.get("risky_idx", [])
        fire_alert(
            f"압력 위험 경고: {len(risky_idx)}개 셀이 critical_time을 초과했습니다."
        )
        warning_store.log_event(data, record["received_at"])
        return record["received_at"]

    @app.post("/event")
    def post_event():
        state.touch()
        data = request.get_json(force=True)
        received_at = _handle_event(data)
        return jsonify({"status": "ok", "received_at": received_at}), 200

    @app.post("/api/mock-warning")
    def post_mock_warning():
        """모의 경고 발생: Calib31.CSV 1000번째 행에서 뽑아 둔 실측 압력
        데이터(mock_warning_data.json)를 현재 config 임계값에 대입해 실제
        /event와 동일한 형태의 위험 경고를 만들어낸다."""
        state.touch()
        mock = _load_mock_warning_data()
        pressure = mock["pressure"]
        config = state.get_config()
        threshold = config["critical_pressure"] / config["calibration_factor"]
        mask_excluded_idx = set(config.get("mask_excluded_idx", []))
        pressure_mask_idx = [i for i, p in enumerate(pressure) if p > 0]
        risky_idx = [
            i for i, p in enumerate(pressure)
            if p > threshold and i not in mask_excluded_idx
        ]
        data = {
            "accumulated_time": config["critical_time"],
            "risky_idx": risky_idx,
            "risky_pressure": [pressure[i] for i in risky_idx],
            "pressure_mask_idx": pressure_mask_idx,
        }
        received_at = _handle_event(data, log_prefix="MOCK EVENT")
        return jsonify({"status": "ok", "received_at": received_at}), 200

    @app.get("/command")
    def get_command():
        state.touch()
        return jsonify({"command": state.consume_command()})

    @app.put("/command")
    def put_command():
        body = request.get_json(force=True)
        command = body.get("command")
        state.set_command(command)
        app.logger.info("command queued -> %s", command)
        return jsonify({"status": "ok", "command": command})

    @app.post("/state")
    def post_state():
        state.touch()
        data = request.get_json(force=True)
        state.record_state(data)
        app.logger.info(
            "STATE timestamp=%s cells=%d",
            data.get("timestamp"),
            len(data.get("pressure", [])),
        )
        return jsonify({"status": "ok"}), 200

    @app.post("/image")
    def post_image():
        state.touch()
        file = request.files.get("image")
        if file is None:
            return jsonify({"status": "error", "message": "missing 'image' file"}), 400
        image_bytes = file.read()
        state.record_image(image_bytes)
        received_at = time.time()
        saved_path = warning_store.save_image(image_bytes, received_at)
        app.logger.info("IMAGE received (%d bytes) -> %s", len(image_bytes), saved_path)
        return jsonify({"status": "ok", "received_at": received_at}), 200

    @app.get("/image/latest")
    def get_latest_image():
        image_bytes = state.get_latest_image()
        if image_bytes is None:
            return jsonify({"status": "error", "message": "no image yet"}), 404
        return send_file(io.BytesIO(image_bytes), mimetype="image/png")

    @app.get("/dashboard")
    def dashboard():
        return render_template("dashboard.html")

    @app.get("/api/meta")
    def api_meta():
        return jsonify({"warning_dir": str(warning_store.base_dir.resolve())})

    @app.get("/api/defaults")
    def api_defaults():
        return jsonify({
            "cols": DEFAULT_COLS,
            "rows": DEFAULT_ROWS,
            "calibration_factor": DEFAULT_CALIBRATION_FACTOR,
            "critical_pressure": DEFAULT_CRITICAL_PRESSURE,
            "critical_time": DEFAULT_CRITICAL_TIME,
            "mask_excluded_idx": [],
        })

    @app.get("/api/history")
    def api_history():
        limit = request.args.get("limit", default=50, type=int)
        records = warning_store.read_history(limit=limit)
        cols = state.snapshot()["cols"]
        for record in records:
            record["risky_cells"] = idx_to_rowcol(record.get("risky_idx", []), cols)
        return jsonify({"history": records})

    @app.post("/api/history/site")
    def api_history_site():
        body = request.get_json(force=True)
        received_at = body.get("received_at")
        site = body.get("site", "")
        if received_at is None:
            return jsonify({"status": "error", "message": "received_at required"}), 400
        found = warning_store.annotate_site(received_at, site)
        if not found:
            return jsonify({"status": "error", "message": "no matching warning"}), 404
        return jsonify({"status": "ok"})

    @app.get("/api/latest")
    def api_latest():
        snap = state.snapshot()
        cols = snap["cols"]
        latest_event = snap["latest_event"]
        if latest_event is not None:
            latest_event["risky_cells"] = idx_to_rowcol(latest_event.get("risky_idx", []), cols)
            latest_event["pressure_mask_cells"] = idx_to_rowcol(
                latest_event.get("pressure_mask_idx", []), cols
            )
        return jsonify({
            "cols": cols,
            "rows": snap["rows"],
            "mask_excluded_cells": idx_to_rowcol(snap.get("mask_excluded_idx", []), cols),
            "has_warning": latest_event is not None,
            "latest_event": latest_event,
            "latest_state": snap["latest_state"],
            "has_image": snap["has_image"],
            "connected": snap["connected"],
            "last_seen": snap["last_seen"],
        })

    app.config["_state"] = state
    app.config["_connection_monitor"] = connection_monitor
    return app


def build_parser():
    p = argparse.ArgumentParser(prog="server.app", description="Pressure risk monitoring server")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--cols", type=int, default=32)
    p.add_argument("--rows", type=int, default=64)
    p.add_argument("--warning-dir", default=DEFAULT_WARNING_DIR,
                    help="directory to log warnings.log and images/ into")
    p.add_argument("--client-timeout", type=float, default=DEFAULT_CLIENT_TIMEOUT_S,
                    help="seconds of silence before the client is considered disconnected")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    app = create_app(
        ServerState(cols=args.cols, rows=args.rows),
        warning_dir=args.warning_dir,
        client_timeout_s=args.client_timeout,
    )
    print(f" * Dashboard: http://localhost:{args.port}/dashboard")
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
