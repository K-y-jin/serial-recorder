import time
from unittest.mock import MagicMock

import pytest

from client.config import RuntimeConfig
from client.http_client import CommandPoller, ConfigPoller, EventSender, StateSender


class FakeResponse:
    def __init__(self, json_data=None, status=200):
        self._json = json_data or {}
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


def test_config_poller_updates_runtime_config_on_success():
    session = MagicMock()
    session.get.return_value = FakeResponse(
        {"calibration_factor": 0.7, "critical_pressure": 20.0, "critical_time": 45.0}
    )
    rc = RuntimeConfig()
    poller = ConfigPoller("http://x", "/config", 60.0, rc, session=session)
    poller.poll_once()
    assert rc.get() == (0.7, 20.0, 45.0)


def test_config_poller_keeps_last_good_value_on_failure():
    session = MagicMock()
    session.get.side_effect = RuntimeError("network down")
    rc = RuntimeConfig(0.5, 32.0, 90.0)
    poller = ConfigPoller("http://x", "/config", 60.0, rc, session=session)
    with pytest.raises(RuntimeError):
        poller.poll_once()
    assert rc.get() == (0.5, 32.0, 90.0)


def test_config_poller_loop_survives_repeated_failures(monkeypatch):
    session = MagicMock()
    session.get.side_effect = RuntimeError("network down")
    rc = RuntimeConfig()
    statuses = []
    poller = ConfigPoller("http://x", "/config", 0.01, rc, session=session,
                           on_status=lambda ok, msg: statuses.append(ok))
    poller.start()
    time.sleep(0.1)
    poller.stop()
    assert any(s is False for s in statuses)


def test_event_sender_posts_payload():
    session = MagicMock()
    session.post.return_value = FakeResponse(status=200)
    sent = []
    sender = EventSender("http://x", "/event", session=session, retry_delay_s=0.01,
                          on_status=lambda ok, msg: sent.append((ok, msg)))
    sender.start()
    sender.enqueue({"accumulated_time": 90.0, "risky_idx": [1], "pressure_mask_idx": [1]})
    time.sleep(0.2)
    sender.stop()
    session.post.assert_called_once()
    assert any(ok for ok, _ in sent)


def test_event_sender_drops_oldest_when_queue_full():
    session = MagicMock()
    session.post.return_value = FakeResponse(status=200)
    sender = EventSender("http://x", "/event", session=session, maxsize=1)
    sender.enqueue({"n": 1})
    sender.enqueue({"n": 2})  # queue full -> drop {"n": 1}, keep {"n": 2}
    assert sender._queue.qsize() == 1
    assert sender._queue.get_nowait() == {"n": 2}


def test_event_sender_gives_up_after_max_attempts():
    session = MagicMock()
    session.post.side_effect = RuntimeError("network down")
    sender = EventSender("http://x", "/event", session=session, retry_delay_s=0.01)
    sender._send({"n": 1})  # should not raise, should give up after MAX_ATTEMPTS
    assert session.post.call_count == EventSender.MAX_ATTEMPTS


def test_command_poller_invokes_callback_on_pending_command():
    session = MagicMock()
    session.get.return_value = FakeResponse({"command": "pause"})
    received = []
    poller = CommandPoller("http://x", "/command", 60.0, received.append, session=session)
    poller.poll_once()
    assert received == ["pause"]


def test_command_poller_ignores_null_command():
    session = MagicMock()
    session.get.return_value = FakeResponse({"command": None})
    received = []
    poller = CommandPoller("http://x", "/command", 60.0, received.append, session=session)
    poller.poll_once()
    assert received == []


def test_command_poller_loop_survives_failures():
    session = MagicMock()
    session.get.side_effect = RuntimeError("network down")
    statuses = []
    poller = CommandPoller("http://x", "/command", 0.01, lambda cmd: None, session=session,
                            on_status=lambda ok, msg: statuses.append(ok))
    poller.start()
    time.sleep(0.1)
    poller.stop()
    assert any(s is False for s in statuses)


def test_state_sender_posts_latest_pressure():
    session = MagicMock()
    session.post.return_value = FakeResponse(status=200)
    sender = StateSender("http://x", "/state", session=session, retry_delay_s=0.01)
    sender.start()
    sender.enqueue({"timestamp": 1.0, "pressure": [1, 2, 3]})
    time.sleep(0.2)
    sender.stop()
    session.post.assert_called_once()
    _, kwargs = session.post.call_args
    assert kwargs["json"] == {"timestamp": 1.0, "pressure": [1, 2, 3]}
