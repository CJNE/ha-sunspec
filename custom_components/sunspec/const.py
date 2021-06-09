"""Constants for SunSpec."""
# Base component constants
NAME = "SunSpec"
DOMAIN = "sunspec"
DOMAIN_DATA = f"{DOMAIN}_data"
VERSION = "0.0.1"

ATTRIBUTION = "Data provided by SunSpec alliance - https://sunspec.org"
ISSUE_URL = "https://github.com/cjne/ha-sunspec/issues"

# Icons
ICON = "mdi:format-quote-close"

# Device classes
BINARY_SENSOR_DEVICE_CLASS = "connectivity"

# Platforms
BINARY_SENSOR = "binary_sensor"
SENSOR = "sensor"
SWITCH = "switch"
PLATFORMS = [SENSOR]


# Configuration and options
CONF_ENABLED = "enabled"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_SLAVE_ID = "slave_id"
CONF_ENABLED_MODELS = "models_enabled"

DEFAULT_MODELS = set(
    [
        101,
        102,
        103,
        201,
        202,
        203,
        204,
        307,
        308,
        401,
        402,
        403,
        404,
        501,
        502,
        601,
        701,
        801,
        802,
        803,
        804,
        805,
        806,
        808,
        809,
    ]
)
# Defaults
DEFAULT_NAME = DOMAIN

STATE_NAMES = [
    "Unknonwn",
    "Off",
    "Sleeping",
    "Starting",
    "Mppt",
    "Throttled",
    "Shutting down",
    "Fault",
    "Standby",
]


STARTUP_MESSAGE = f"""
-------------------------------------------------------------------
{NAME}
Version: {VERSION}
This is a custom integration!
If you have any issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""
