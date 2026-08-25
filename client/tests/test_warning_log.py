import json

from client.warning_log import WarningLog


def test_log_warning_appends_json_line(tmp_path):
    wl = WarningLog(tmp_path / "warnings", clock=lambda: 1.0)
    wl.log_warning({"accumulated_time": 90.0, "risky_idx": [0, 5]})

    lines = (tmp_path / "warnings" / "warnings.log").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["risky_idx"] == [0, 5]
    assert record["logged_at"] == 1.0


def test_save_image_writes_file_named_by_timestamp(tmp_path):
    wl = WarningLog(tmp_path / "warnings", clock=lambda: 2.0)
    path = wl.save_image(b"\x89PNGfake", ts=123.456789)

    saved = tmp_path / "warnings" / "images" / "123.456789.png"
    assert str(saved) == path
    assert saved.read_bytes() == b"\x89PNGfake"


def test_log_send_records_outcome(tmp_path):
    wl = WarningLog(tmp_path / "warnings", clock=lambda: 3.0)
    wl.log_send("event", True, "event sent")
    wl.log_send("image", False, "image send failed, dropping: timeout")

    lines = (tmp_path / "warnings" / "send.log").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    r1, r2 = (json.loads(line) for line in lines)
    assert r1 == {"kind": "event", "ok": True, "message": "event sent", "logged_at": 3.0}
    assert r2["kind"] == "image"
    assert r2["ok"] is False
