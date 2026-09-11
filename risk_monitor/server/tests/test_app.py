import io
import json

import pytest

from server.app import create_app
from server.state import ServerState


@pytest.fixture
def client(tmp_path):
    app = create_app(ServerState(cols=4, rows=4), warning_dir=tmp_path / "warnings")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
    app.config["_connection_monitor"].stop()


def test_default_does_not_reprompt_after_a_later_restart_with_no_changes(tmp_path):
    warning_dir = tmp_path / "warnings"

    def start():
        app = create_app(ServerState(cols=4, rows=4), warning_dir=warning_dir)
        app.config["TESTING"] = True
        return app

    def stop(app):
        app.config["_connection_monitor"].stop()

    # Run 1: user changes a setting, which gets persisted.
    app1 = start()
    with app1.test_client() as c1:
        c1.put("/config", json={"critical_pressure": 55.0})
    stop(app1)

    # Run 2 (restart): sees the saved config as pending, user picks "기본값 사용".
    app2 = start()
    with app2.test_client() as c2:
        assert c2.get("/api/config/pending").get_json()["pending"] is True
        c2.post("/api/config/pending/resolve", json={"action": "default"})
    stop(app2)
    assert not (warning_dir / "config.json").exists()

    # Run 3 (restart, no user changes at all): must NOT recreate config.json,
    # or run 4 would wrongly see it as a pending restore again.
    app3 = start()
    stop(app3)
    assert not (warning_dir / "config.json").exists()

    app4 = start()
    with app4.test_client() as c4:
        assert c4.get("/api/config/pending").get_json()["pending"] is False
    stop(app4)


def test_get_config_defaults(client):
    resp = client.get("/config")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["cols"] == 4
    assert data["rows"] == 4
    assert data["calibration_factor"] == 0.4755


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


def test_event_clear_partially_resolves_warning(client):
    client.post("/event", json={
        "accumulated_time": 90.0,
        "risky_idx": [0, 5],
        "risky_pressure": [40.0, 41.0],
        "pressure_mask_idx": [0, 1, 5, 6],
    })

    resp = client.post("/event/clear", json={"cleared_idx": [0]})
    assert resp.status_code == 200

    latest = client.get("/api/latest").get_json()
    assert latest["has_warning"] is True
    assert latest["latest_event"]["risky_idx"] == [5]
    assert latest["latest_event"]["risky_pressure"] == [41.0]


def test_event_clear_drops_warning_once_all_cells_resolved(client):
    client.post("/event", json={
        "accumulated_time": 90.0,
        "risky_idx": [0, 5],
        "pressure_mask_idx": [0, 1, 5, 6],
    })

    client.post("/event/clear", json={"cleared_idx": [0, 5]})

    latest = client.get("/api/latest").get_json()
    assert latest["has_warning"] is False
    assert latest["latest_event"] is None


def test_event_clear_with_no_active_warning_is_a_noop(client):
    resp = client.post("/event/clear", json={"cleared_idx": [0]})
    assert resp.status_code == 200
    assert client.get("/api/latest").get_json()["has_warning"] is False


def test_api_latest_no_warning_initially(client):
    data = client.get("/api/latest").get_json()
    assert data["has_warning"] is False
    assert data["latest_event"] is None
    assert data["cols"] == 4
    assert data["rows"] == 4


def test_dashboard_smoke(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200


def test_event_is_logged_to_warnings_file(client, tmp_path):
    client.post("/event", json={
        "accumulated_time": 90.0,
        "risky_idx": [0, 5],
        "pressure_mask_idx": [0, 1, 5, 6],
    })
    log_path = tmp_path / "warnings" / "default" / "warnings.log"
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["risky_idx"] == [0, 5]
    assert "received_at" in record


def test_mock_warning_is_tagged_and_clearable(client, tmp_path):
    client.post("/event", json={
        "accumulated_time": 90.0,
        "risky_idx": [0, 5],
        "pressure_mask_idx": [0, 1, 5, 6],
    })
    client.post("/api/mock-warning")

    log_path = tmp_path / "warnings" / "default" / "warnings.log"
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    assert records[0].get("is_mock") is not True
    assert records[1]["is_mock"] is True

    image_dir = tmp_path / "warnings" / "default" / "images"
    mock_images = list(image_dir.glob("mock_*.png"))
    assert len(mock_images) == 1

    resp = client.post("/api/mock-warning/clear")
    assert resp.status_code == 200
    assert resp.get_json()["removed"] == 1

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]).get("is_mock") is not True
    assert list(image_dir.glob("mock_*.png")) == []

    latest_event = client.get("/api/latest").get_json()["latest_event"]
    assert latest_event["risky_idx"] == [0, 5]


def test_clearing_mock_warning_drops_latest_event_when_no_real_event(client):
    client.post("/api/mock-warning")
    assert client.get("/api/latest").get_json()["latest_event"] is not None

    client.post("/api/mock-warning/clear")
    assert client.get("/api/latest").get_json()["latest_event"] is None


def test_image_is_saved_to_warnings_dir(client, tmp_path):
    resp = client.post(
        "/image",
        data={"image": (io.BytesIO(b"\x89PNGfake"), "risk.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200

    image_dir = tmp_path / "warnings" / "default" / "images"
    saved = list(image_dir.glob("*.png"))
    assert len(saved) == 1
    assert saved[0].read_bytes() == b"\x89PNGfake"

    assert client.get("/api/latest").get_json()["has_image"] is True


def test_image_status_saved_when_state_known(client, tmp_path):
    client.post("/state", json={"timestamp": 1.0, "pressure": [1, 2, 3, 4]})
    client.post(
        "/image",
        data={"image": (io.BytesIO(b"\x89PNGfake"), "risk.png")},
        content_type="multipart/form-data",
    )

    image_dir = tmp_path / "warnings" / "default" / "images"
    statuses = list(image_dir.glob("*.json"))
    assert len(statuses) == 1
    status = json.loads(statuses[0].read_text(encoding="utf-8"))
    assert status["pressure"] == [1, 2, 3, 4]
    assert status["cols"] == 4
    assert status["rows"] == 4


def test_state_request_saves_status_image(client, tmp_path):
    client.post("/state", json={"timestamp": 1.0, "pressure": [0] * 16})

    image_dir = tmp_path / "warnings" / "default" / "images"
    pngs = list(image_dir.glob("status_*.png"))
    jsons = list(image_dir.glob("status_*.json"))
    assert len(pngs) == 1
    assert len(jsons) == 1
    status = json.loads(jsons[0].read_text(encoding="utf-8"))
    assert status["pressure"] == [0] * 16
    assert status["cols"] == 4
    assert status["rows"] == 4


def test_mock_warning_status_is_saved_and_cleared(client, tmp_path):
    client.post("/api/mock-warning")

    image_dir = tmp_path / "warnings" / "default" / "images"
    mock_statuses = list(image_dir.glob("mock_*.json"))
    assert len(mock_statuses) == 1
    status = json.loads(mock_statuses[0].read_text(encoding="utf-8"))
    assert "pressure" in status and "cols" in status and "rows" in status

    client.post("/api/mock-warning/clear")
    assert list(image_dir.glob("mock_*.json")) == []


def test_client_requests_touch_connection_state(client):
    data = client.get("/api/latest").get_json()
    assert data["connected"] is None
    assert data["last_seen"] is None

    client.get("/config")
    data = client.get("/api/latest").get_json()
    assert data["last_seen"] is not None


def test_multiple_clients_do_not_share_state(client, tmp_path):
    client.put("/config?client_id=a", json={"critical_pressure": 10.0})
    client.put("/config?client_id=b", json={"critical_pressure": 99.0})

    a_config = client.get("/config?client_id=a").get_json()
    b_config = client.get("/config?client_id=b").get_json()
    assert a_config["critical_pressure"] == 10.0
    assert b_config["critical_pressure"] == 99.0

    client.post("/event?client_id=a", json={
        "accumulated_time": 90.0, "risky_idx": [1], "pressure_mask_idx": [1],
    })
    a_latest = client.get("/api/latest?client_id=a").get_json()
    b_latest = client.get("/api/latest?client_id=b").get_json()
    assert a_latest["has_warning"] is True
    assert b_latest["has_warning"] is False

    assert (tmp_path / "warnings" / "a" / "warnings.log").exists()
    assert not (tmp_path / "warnings" / "b" / "warnings.log").exists()


def test_api_clients_lists_known_clients(client):
    client.get("/config?client_id=a")
    client.get("/config?client_id=b")
    client.post("/event?client_id=b", json={
        "accumulated_time": 90.0, "risky_idx": [1], "pressure_mask_idx": [1],
    })

    data = client.get("/api/clients").get_json()
    by_id = {c["client_id"]: c for c in data["clients"]}
    assert set(by_id) == {"a", "b"}
    assert by_id["a"]["has_warning"] is False
    assert by_id["b"]["has_warning"] is True
