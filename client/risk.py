"""Per-cell risk accumulation for the pressure-monitoring client.

risk_mask = pressure_vector > (critical_pressure / calibration_factor)
accumulated_risk = (accumulated_risk + risk_mask * dt_minutes) * risk_mask

`dt_minutes` is derived from wall-clock elapsed time (not tick count) so the
critical_time comparison stays accurate regardless of jitter in the frame
arrival rate.
"""
import time

import numpy as np


class RiskAccumulator:
    def __init__(self, n_cells, alert_cooldown_s=300.0, clock=time.monotonic):
        self.n_cells = n_cells
        self.alert_cooldown_s = alert_cooldown_s
        self._clock = clock
        self.accumulated_risk = np.zeros(n_cells, dtype=np.float64)
        self.last_alert_time = np.full(n_cells, -np.inf, dtype=np.float64)
        self._last_tick_ts = None

    def update(self, pressure_vector, calibration_factor, critical_pressure,
               critical_time, now=None):
        """Advance the accumulator by one frame.

        Returns (fired_idx, risk_mask):
          - risk_mask: bool array, cells currently over the pressure threshold
          - fired_idx: int array, cells that just reached critical_time AND
            are past their alert cooldown (i.e. should be reported now)
        """
        if pressure_vector.shape[0] != self.n_cells:
            raise ValueError(
                f"pressure_vector has {pressure_vector.shape[0]} cells, "
                f"expected {self.n_cells}"
            )
        now = self._clock() if now is None else now
        if self._last_tick_ts is None:
            dt_min = 0.0
        else:
            dt_min = max(0.0, now - self._last_tick_ts) / 60.0
        self._last_tick_ts = now

        threshold = critical_pressure / calibration_factor
        risk_mask = pressure_vector > threshold

        self.accumulated_risk = (self.accumulated_risk + risk_mask * dt_min) * risk_mask

        reached = self.accumulated_risk >= critical_time
        cooldown_ok = (now - self.last_alert_time) >= self.alert_cooldown_s
        fired_mask = reached & cooldown_ok
        fired_idx = np.nonzero(fired_mask)[0]
        if fired_idx.size:
            self.last_alert_time[fired_idx] = now
        return fired_idx, risk_mask

    def reset(self):
        """Zero out accumulated_risk (the `reset` command). Alert cooldowns
        are left untouched -- only the accumulated risk itself is cleared."""
        self.accumulated_risk = np.zeros(self.n_cells, dtype=np.float64)

    def resync(self):
        """Forget the last tick timestamp so the next update() computes
        dt=0 instead of a large jump. Must be called whenever monitoring
        resumes after being paused/stopped, since no update() calls (and
        therefore no elapsed-time accounting) happened while inactive."""
        self._last_tick_ts = None
