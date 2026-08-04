"""End-to-end: mock server + ClientApp in --dry-run mode, verifying that a
persistently hot cell eventually produces a POST /event call."""
import socket
import threading
import time

import pytest
import requests

from client.main import ClientApp, build_parser
from client.mock_server.server import create_app


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def mock_server():
    port = _free_port()
    app = create_app({"calibration_factor": 0.5, "critical_pressure": 1.0, "critical_time": 0.01})
    thread = threading.Thread(
        target=app.run, kwargs={"host": "127.0.0.1", "port": port, "use_reloader": False},
        daemon=True,
    )
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            requests.get(base_url + "/config", timeout=0.2)
            break
        except Exception:
            time.sleep(0.1)
    yield app, base_url


def _make_client_app(base_url, **overrides):
    argv = [
        "--dry-run", "--dry-fps", "30",
        "--cols", "4", "--rows", "4",
        "--server-url", base_url,
        "--poll-interval", "0.2",
        "--command-poll-interval", "0.1",
        "--alert-cooldown", "0.1",
    ]
    for k, v in overrides.items():
        argv += [f"--{k.replace('_', '-')}", str(v)]
    args = build_parser().parse_args(argv)
    return ClientApp(args)


def _start_all(client_app):
    client_app.reader.start()
    client_app.poller.start()
    client_app.command_poller.start()
    client_app.sender.start()
    client_app.state_sender.start()


def _stop_all(client_app):
    client_app.reader.stop()
    client_app.poller.stop()
    client_app.command_poller.stop()
    client_app.sender.stop()
    client_app.state_sender.stop()


def test_dry_run_client_reports_event_to_mock_server(mock_server):
    app, base_url = mock_server
    client_app = _make_client_app(base_url)
    _start_all(client_app)
    try:
        deadline = time.time() + 5.0
        while time.time() < deadline and len(app.config["_events"]) == 0:
            time.sleep(0.1)
    finally:
        _stop_all(client_app)

    events = app.config["_events"]
    assert events, "expected at least one /event call from the persistently hot cell"
    ev = events[0]
    assert ev["risky_idx"], "risky_idx should be non-empty"
    assert "accumulated_time" in ev
    assert "pressure_mask_idx" in ev


def test_pause_command_stops_events_and_reset_command_resumes(mock_server):
    app, base_url = mock_server
    client_app = _make_client_app(base_url)
    _start_all(client_app)
    try:
        requests.put(base_url + "/command", json={"command": "pause"}, timeout=1.0)
        deadline = time.time() + 2.0
        while time.time() < deadline and client_app.monitor.state != "paused":
            time.sleep(0.05)
        assert client_app.monitor.state == "paused"

        # While paused, no new events should be produced even though the
        # hot cell keeps streaming pressure frames.
        time.sleep(0.5)
        assert len(app.config["_events"]) == 0

        requests.put(base_url + "/command", json={"command": "reset"}, timeout=1.0)
        deadline = time.time() + 2.0
        while time.time() < deadline and len(app.config["_events"]) == 0:
            time.sleep(0.1)
    finally:
        _stop_all(client_app)

    assert len(app.config["_events"]) > 0
    assert client_app.monitor.state == "running"


def test_state_command_triggers_state_report(mock_server):
    app, base_url = mock_server
    client_app = _make_client_app(base_url)
    _start_all(client_app)
    try:
        # Let at least one frame arrive so latest_frame is populated.
        deadline = time.time() + 2.0
        while time.time() < deadline and client_app.latest_frame.get()[1] is None:
            time.sleep(0.05)

        requests.put(base_url + "/command", json={"command": "state"}, timeout=1.0)
        deadline = time.time() + 2.0
        while time.time() < deadline and len(app.config["_state_reports"]) == 0:
            time.sleep(0.1)
    finally:
        _stop_all(client_app)

    reports = app.config["_state_reports"]
    assert reports, "expected a /state report after the state command"
    assert len(reports[0]["pressure"]) == 16  # cols*rows = 4*4
