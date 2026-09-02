"""Risk warning fired when the server receives a client risk warning
(POST /event). The dashboard (server/templates/dashboard.html) owns the
actual alert sound/popup shown to the user, so this only logs."""
import logging

logger = logging.getLogger(__name__)


def fire_alert(message):
    logger.warning("RISK ALERT: %s", message)
