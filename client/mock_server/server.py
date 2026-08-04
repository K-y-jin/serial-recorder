"""Minimal mock server for end-to-end testing of client/main.py.

Endpoints:
  GET  /config   -> {"calibration_factor": ..., "critical_pressure": ..., "critical_time": ...}
  PUT  /config   -> update the in-memory config (test convenience, not part of the real spec)
  POST /event    -> logs {"accumulated_time", "risky_idx", "pressure_mask_idx"} and returns 200
  GET  /command  -> {"command": "start"|"pause"|"stop"|"reset"|"state"|null}, consumed once
  PUT  /command  -> queue a pending command (test convenience)
  POST /state    -> logs {"pressure", "timestamp"} (client's answer to a "state" command)

Usage:
    python -m client.mock_server.server [--host 0.0.0.0] [--port 5000]
"""
import argparse
import logging
import threading

from flask import Flask, jsonify, request

DEFAULT_STATE = {
    "calibration_factor": 0.5,
    "critical_pressure": 32.0,
    "critical_time": 90.0,
}


def create_app(initial_state=None):
    app = Flask(__name__)
    app.logger.setLevel(logging.INFO)
    state = dict(initial_state or DEFAULT_STATE)
    lock = threading.Lock()
    events = []
    pending_command = {"command": None}
    state_reports = []

    @app.get("/config")
    def get_config():
        with lock:
            return jsonify(dict(state))

    @app.put("/config")
    def put_config():
        body = request.get_json(force=True)
        with lock:
            state.update(body)
            snapshot = dict(state)
        app.logger.info("config updated -> %s", snapshot)
        return jsonify(snapshot)

    @app.post("/event")
    def post_event():
        data = request.get_json(force=True)
        with lock:
            events.append(data)
        app.logger.info(
            "EVENT accumulated_time=%s risky_idx=%s pressure_mask_idx=%d cells",
            data.get("accumulated_time"),
            data.get("risky_idx"),
            len(data.get("pressure_mask_idx", [])),
        )
        return jsonify({"status": "ok"}), 200

    @app.get("/command")
    def get_command():
        with lock:
            cmd = pending_command["command"]
            pending_command["command"] = None  # each queued command is delivered once
        return jsonify({"command": cmd})

    @app.put("/command")
    def put_command():
        body = request.get_json(force=True)
        with lock:
            pending_command["command"] = body.get("command")
        app.logger.info("command queued -> %s", pending_command["command"])
        return jsonify({"status": "ok", "command": pending_command["command"]})

    @app.post("/state")
    def post_state():
        data = request.get_json(force=True)
        with lock:
            state_reports.append(data)
        app.logger.info(
            "STATE timestamp=%s cells=%d",
            data.get("timestamp"),
            len(data.get("pressure", [])),
        )
        return jsonify({"status": "ok"}), 200

    app.config["_state"] = state
    app.config["_events"] = events
    app.config["_pending_command"] = pending_command
    app.config["_state_reports"] = state_reports
    app.config["_lock"] = lock
    return app


def build_parser():
    p = argparse.ArgumentParser(prog="client.mock_server", description="Mock threshold server")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=5000)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    app = create_app()
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
