"""Sound + popup alert fired when the server receives a client risk
warning (POST /event). Windows-only (winsound/ctypes); a no-op elsewhere
so the same server code runs unmodified during development on Linux/mac
and under pytest."""
import logging
import platform
import threading

logger = logging.getLogger(__name__)

IS_WINDOWS = platform.system() == "Windows"


def fire_alert(message):
    """Beep and show a popup on Windows; log-only elsewhere. Runs the
    popup in a background thread so it never blocks the Flask request
    handling it while a person acknowledges the dialog."""
    if not IS_WINDOWS:
        logger.warning("RISK ALERT (no popup outside Windows): %s", message)
        return

    def _show():
        import ctypes
        import winsound
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        MB_ICONWARNING = 0x30
        MB_TOPMOST = 0x40000
        ctypes.windll.user32.MessageBoxW(0, message, "Bliss Server - 위험 경고", MB_ICONWARNING | MB_TOPMOST)

    threading.Thread(target=_show, daemon=True).start()
