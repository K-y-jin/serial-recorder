"""Real server for the pressure risk monitoring client.

Implements the same REST contract as client/mock_server/server.py (GET/PUT
/config, POST /event, GET/PUT /command, POST /state) plus a dashboard that
visualizes the latest risk warning: pressure_mask_idx (cells under body
pressure -- the mattress "silhouette") shaded as background, risky_idx
(cells that exceeded critical_time) highlighted on top.

Endpoints:
  GET  /config      -> {"cols", "rows", "calibration_factor", "critical_pressure", "critical_time"}
  PUT  /config      -> update thresholds/grid size, returns the new config
  POST /event       -> client risk warning: {"accumulated_time", "risky_idx", "pressure_mask_idx"}
  GET  /command     -> {"command": "start"|"pause"|"stop"|"reset"|"state"|null}, consumed once
  PUT  /command     -> queue a pending command: {"command": "..."}
  POST /state       -> client's answer to a "state" command: {"timestamp", "pressure"}
  GET  /dashboard   -> HTML dashboard
  GET  /api/latest  -> JSON snapshot for the dashboard poller

Usage:
    python -m server.app [--host 0.0.0.0] [--port 8000]
                          [--cols 32] [--rows 64]
"""
import argparse
import logging

from flask import Flask, jsonify, render_template, request

from server.grid import idx_to_rowcol
from server.state import ServerState


def create_app(state=None):
    app = Flask(__name__)
    app.logger.setLevel(logging.INFO)
    state = state or ServerState()

    @app.get("/config")
    def get_config():
        return jsonify(state.get_config())

    @app.put("/config")
    def put_config():
        body = request.get_json(force=True)
        snapshot = state.update_config(body)
        app.logger.info("config updated -> %s", snapshot)
        return jsonify(snapshot)

    @app.post("/event")
    def post_event():
        data = request.get_json(force=True)
        record = state.record_event(data)
        app.logger.info(
            "EVENT accumulated_time=%s risky_idx=%s pressure_mask_idx=%d cells",
            data.get("accumulated_time"),
            data.get("risky_idx"),
            len(data.get("pressure_mask_idx", [])),
        )
        return jsonify({"status": "ok", "received_at": record["received_at"]}), 200

    @app.get("/command")
    def get_command():
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
        data = request.get_json(force=True)
        state.record_state(data)
        app.logger.info(
            "STATE timestamp=%s cells=%d",
            data.get("timestamp"),
            len(data.get("pressure", [])),
        )
        return jsonify({"status": "ok"}), 200

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
        })

    app.config["_state"] = state
    return app


def build_parser():
    p = argparse.ArgumentParser(prog="server.app", description="Pressure risk monitoring server")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--cols", type=int, default=64)
    p.add_argument("--rows", type=int, default=32)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    app = create_app(ServerState(cols=args.cols, rows=args.rows))
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
