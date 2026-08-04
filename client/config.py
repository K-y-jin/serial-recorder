"""Client-local configuration: static CLI/file settings plus the
server-managed runtime thresholds (calibration_factor, critical_pressure,
critical_time), which are refreshed by periodic polling."""
import threading
from dataclasses import dataclass

DEFAULT_CALIBRATION_FACTOR = 0.5
DEFAULT_CRITICAL_PRESSURE = 32.0  # mmHg
DEFAULT_CRITICAL_TIME = 90.0  # minutes
DEFAULT_PRESSURE_MASK_THRESHOLD = 10  # fixed, not server-configurable


@dataclass(frozen=True)
class ClientConfig:
    port: str = "/dev/ttyUSB0"
    baud: int = 921600
    cols: int = 32
    rows: int = 64
    header_hex: str = "A55A"
    pre_skip: int = 6
    post_skip: int = 2

    server_base_url: str = "http://localhost:5000"
    config_path: str = "/config"
    event_path: str = "/event"
    command_path: str = "/command"
    state_path: str = "/state"
    poll_interval_s: float = 60.0
    command_poll_interval_s: float = 2.0
    http_timeout_s: float = 5.0
    http_retry_delay_s: float = 5.0
    alert_cooldown_s: float = 300.0
    pressure_mask_threshold: int = DEFAULT_PRESSURE_MASK_THRESHOLD
    event_queue_maxsize: int = 64


class RuntimeConfig:
    """Thread-safe holder for the three server-managed thresholds.

    `update()` swaps the whole snapshot tuple atomically so a concurrent
    `get()` from the frame-processing thread never observes a torn mix of
    old/new values. Updating never touches accumulated_risk state — new
    values simply apply starting with the next `RiskAccumulator.update()`
    call.
    """

    def __init__(self,
                 calibration_factor=DEFAULT_CALIBRATION_FACTOR,
                 critical_pressure=DEFAULT_CRITICAL_PRESSURE,
                 critical_time=DEFAULT_CRITICAL_TIME):
        self._lock = threading.Lock()
        self._snapshot = (calibration_factor, critical_pressure, critical_time)

    def update(self, calibration_factor, critical_pressure, critical_time):
        with self._lock:
            self._snapshot = (calibration_factor, critical_pressure, critical_time)

    def get(self):
        with self._lock:
            return self._snapshot
