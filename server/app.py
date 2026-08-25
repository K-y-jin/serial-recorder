"""Real server for the pressure risk monitoring client.

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
  GET  /config      -> {"cols", "rows", "calibration_factor", "critical_pressure", "critical_time"}
  PUT  /config      -> update thresholds/grid size, returns the new config
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

Usage:
    python -m server.app [--host 0.0.0.0] [--port 5000]
                          [--cols 32] [--rows 64] [--warning-dir warnings]
                          [--client-timeout 10.0]
"""
import argparse
import io
import logging
import sys
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from server.alert import fire_alert
from server.connection_monitor import DEFAULT_TIMEOUT_S as DEFAULT_CLIENT_TIMEOUT_S
from server.connection_monitor import ConnectionMonitor
from server.grid import idx_to_rowcol
from server.state import ServerState
from server.warning_store import DEFAULT_DIR as DEFAULT_WARNING_DIR
from server.warning_store import WarningStore


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
    connection_monitor = ConnectionMonitor(state, timeout_s=client_timeout_s)
    connection_monitor.start()

    @app.get("/config")
    def get_config():
        state.touch()
        return jsonify(state.get_config())

    @app.put("/config")
    def put_config():
        body = request.get_json(force=True)
        snapshot = state.update_config(body)
        app.logger.info("config updated -> %s", snapshot)
        return jsonify(snapshot)

    @app.post("/event")
    def post_event():
        state.touch()
        data = request.get_json(force=True)
        record = state.record_event(data)
        app.logger.info(
            "EVENT accumulated_time=%s risky_idx=%s pressure_mask_idx=%d cells",
            data.get("accumulated_time"),
            data.get("risky_idx"),
            len(data.get("pressure_mask_idx", [])),
        )
        risky_idx = data.get("risky_idx", [])
        fire_alert(
            f"압력 위험 경고: {len(risky_idx)}개 셀이 critical_time을 초과했습니다."
        )
        warning_store.log_event(data, record["received_at"])
        return jsonify({"status": "ok", "received_at": record["received_at"]}), 200

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
    p.add_argument("--cols", type=int, default=64)
    p.add_argument("--rows", type=int, default=32)
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
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
