"""Constants for the airCloud Pro (local) integration."""
from datetime import timedelta

DOMAIN = "aircloud_pro_local"
MANUFACTURER = "Hitachi / Johnson Controls"

CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 15  # seconds; the gateway GUI itself polls every 1-5 s
MIN_SCAN_INTERVAL = 5
DEFAULT_TIMEOUT = 10

PLATFORMS = ["climate", "sensor", "binary_sensor"]

UPDATE_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)
