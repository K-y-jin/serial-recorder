import threading
import time
import serial

from .config import RECONNECT_DELAY_S, SERIAL_READ_CHUNK, SERIAL_READ_TIMEOUT_S


class SerialReader:
    def __init__(self, port, baud, parser, on_status=None):
        self.port = port
        self.baud = baud
        self.parser = parser
        self.on_status = on_status or (lambda connected, msg: None)
        self._stop = threading.Event()
        self._thread = None
        self._ser = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._ser = None

    def _run(self):
        while not self._stop.is_set():
            try:
                self.on_status(False, f"Connecting to {self.port}...")
                self._ser = serial.Serial(
                    self.port, self.baud, timeout=SERIAL_READ_TIMEOUT_S
                )
                self.on_status(True, f"Connected to {self.port}")
            except Exception as e:
                self.on_status(False, f"Connect failed: {e}. Retrying...")
                self._sleep(RECONNECT_DELAY_S)
                continue

            try:
                while not self._stop.is_set():
                    data = self._ser.read(SERIAL_READ_CHUNK)
                    if data:
                        self.parser.feed(data)
            except Exception as e:
                self.on_status(False, f"Disconnected: {e}. Reconnecting...")
            finally:
                try:
                    if self._ser is not None:
                        self._ser.close()
                except Exception:
                    pass
                self._ser = None

            if not self._stop.is_set():
                self._sleep(RECONNECT_DELAY_S)

        self.on_status(False, "Stopped")

    def _sleep(self, seconds):
        end = time.time() + seconds
        while time.time() < end and not self._stop.is_set():
            time.sleep(0.05)
