from server.connection_monitor import ConnectionMonitor
from server.state import ServerState


def test_no_alert_before_first_contact(monkeypatch):
    fired = []
    monkeypatch.setattr("server.connection_monitor.fire_alert", fired.append)

    state = ServerState()
    monitor = ConnectionMonitor(state, timeout_s=5.0, clock=lambda: 100.0)
    monitor.check_once()

    assert fired == []
    assert state.is_connected() is None


def test_disconnect_alerts_once(monkeypatch):
    fired = []
    monkeypatch.setattr("server.connection_monitor.fire_alert", fired.append)

    now = [0.0]
    state = ServerState(clock=lambda: now[0])
    monitor = ConnectionMonitor(state, timeout_s=5.0, clock=lambda: now[0])

    state.touch()  # last_seen = 0.0
    now[0] = 1.0
    monitor.check_once()  # within timeout -> connected, no alert (first observation)
    assert fired == []
    assert state.is_connected() is True

    now[0] = 20.0  # well past timeout_s=5.0
    monitor.check_once()
    assert fired == ["클라이언트 연결이 끊어졌습니다."]
    assert state.is_connected() is False

    # Repeated checks while still disconnected must not re-alert.
    now[0] = 25.0
    monitor.check_once()
    assert fired == ["클라이언트 연결이 끊어졌습니다."]


def test_reconnect_alerts(monkeypatch):
    fired = []
    monkeypatch.setattr("server.connection_monitor.fire_alert", fired.append)

    now = [0.0]
    state = ServerState(clock=lambda: now[0])
    monitor = ConnectionMonitor(state, timeout_s=5.0, clock=lambda: now[0])

    state.touch()
    now[0] = 1.0
    monitor.check_once()  # connected

    now[0] = 20.0
    monitor.check_once()  # disconnected
    assert state.is_connected() is False

    state.touch()  # client contacts again at "now"
    now[0] = 21.0
    monitor.check_once()
    assert state.is_connected() is True
    assert fired[-1] == "클라이언트 연결이 복구되었습니다."
