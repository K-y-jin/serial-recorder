import pytest

from server.app import create_app
from server.state import ServerState


@pytest.fixture
def client():
    app = create_app(ServerState(cols=4, rows=4))
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_get_config_defaults(client):
    resp = client.get("/config")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["cols"] == 4
    assert data["rows"] == 4
    assert data["calibration_factor"] == 0.5


def test_put_config_updates_and_returns_full_snapshot(client):
    resp = client.put("/config", json={"critical_time": 45.0})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["critical_time"] == 45.0
    assert data["critical_pressure"] == 32.0

    resp2 = client.get("/config")
    assert resp2.get_json()["critical_time"] == 45.0


def test_command_roundtrip(client):
    assert client.get("/command").get_json() == {"command": None}
    client.put("/command", json={"command": "pause"})
    assert client.get("/command").get_json() == {"command": "pause"}
    assert client.get("/command").get_json() == {"command": None}  # consumed once


def test_state_report_reflected_in_api_latest(client):
    client.post("/state", json={"timestamp": 1.0, "pressure": [10] * 16})
    resp = client.get("/api/latest")
    data = resp.get_json()
    assert data["latest_state"]["pressure"] == [10] * 16
    assert data["has_warning"] is False
    assert data["latest_event"] is None


def test_event_triggers_warning_with_grid_cells(client):
    resp = client.post("/event", json={
        "accumulated_time": 90.0,
        "risky_idx": [0, 5],
        "pressure_mask_idx": [0, 1, 5, 6],
    })
    assert resp.status_code == 200
    assert "received_at" in resp.get_json()

    latest = client.get("/api/latest").get_json()
    assert latest["has_warning"] is True
    ev = latest["latest_event"]
    assert ev["risky_idx"] == [0, 5]
    # cols=4 -> idx 0 -> (0,0), idx 5 -> (1,1)
    assert ev["risky_cells"] == [[0, 0], [1, 1]]
    assert ev["pressure_mask_cells"] == [[0, 0], [0, 1], [1, 1], [1, 2]]
    assert "received_at" in ev


def test_api_latest_no_warning_initially(client):
    data = client.get("/api/latest").get_json()
    assert data["has_warning"] is False
    assert data["latest_event"] is None
    assert data["cols"] == 4
    assert data["rows"] == 4


def test_dashboard_smoke(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert b"Pressure Risk Dashboard" in resp.data
