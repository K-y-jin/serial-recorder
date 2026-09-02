import numpy as np
import pytest

from client.monitor import MonitorState, PAUSED, RUNNING, STOPPED, UnknownCommandError
from client.risk import RiskAccumulator


def test_default_state_is_running():
    acc = RiskAccumulator(n_cells=2)
    mon = MonitorState(acc)
    assert mon.state == RUNNING
    assert mon.is_active() is True


def test_pause_deactivates_without_touching_accumulated_risk():
    acc = RiskAccumulator(n_cells=1)
    pressure = np.array([100], dtype=np.uint8)
    acc.update(pressure, calibration_factor=0.5, critical_pressure=32, critical_time=10)
    acc._last_tick_ts = 100.0
    acc.accumulated_risk[0] = 5.0

    mon = MonitorState(acc)
    assert mon.apply("pause") == PAUSED
    assert mon.is_active() is False
    assert acc.accumulated_risk[0] == 5.0


def test_stop_deactivates():
    acc = RiskAccumulator(n_cells=1)
    mon = MonitorState(acc)
    assert mon.apply("stop") == STOPPED
    assert mon.is_active() is False


def test_start_resumes_and_resyncs_clock():
    acc = RiskAccumulator(n_cells=1)
    acc._last_tick_ts = 100.0
    mon = MonitorState(acc)
    mon.apply("pause")
    assert mon.apply("start") == RUNNING
    assert mon.is_active() is True
    assert acc._last_tick_ts is None  # resynced so next update() dt=0


def test_reset_zeroes_accumulated_risk_and_resumes_running():
    acc = RiskAccumulator(n_cells=2)
    acc.accumulated_risk[:] = [5.0, 7.0]
    acc._last_tick_ts = 100.0
    mon = MonitorState(acc)
    mon.apply("pause")

    assert mon.apply("reset") == RUNNING
    assert acc.accumulated_risk.tolist() == [0.0, 0.0]
    assert acc._last_tick_ts is None
    assert mon.is_active() is True


def test_state_command_does_not_change_monitor_state():
    acc = RiskAccumulator(n_cells=1)
    mon = MonitorState(acc)
    mon.apply("pause")
    result = mon.apply("state")
    assert result is None
    assert mon.state == PAUSED  # unchanged


def test_unknown_command_raises():
    acc = RiskAccumulator(n_cells=1)
    mon = MonitorState(acc)
    with pytest.raises(UnknownCommandError):
        mon.apply("frobnicate")
