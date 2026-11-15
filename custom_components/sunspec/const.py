"""Constants for SunSpec."""

DOMAIN = "sunspec"

# Platforms
SENSOR = "sensor"
PLATFORMS = [SENSOR]


# Configuration and options
CONF_HOST = "host"
CONF_PORT = "port"
CONF_UNIT_ID = "unit_id"
CONF_DEVICE = "device"
CONF_BAUDRATE = "baudrate"
CONF_PARITY = "parity"
CONF_PREFIX = "prefix"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_ENABLED_MODELS = "models_enabled"
CONF_MODEL_INTERVALS = "model_intervals"

DEFAULT_MODELS = set(
    [
        101,
        102,
        103,
        160,
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
# Group names these models had up to pysunspec2 1.1.5. Device identifiers and
# entity names are built from them, so they must not change.
GROUP_NAMES = {
    **dict.fromkeys((101, 102, 103, 111, 112, 113), "inverter"),
    124: "storage",
    **dict.fromkeys((201, 202, 203, 204, 211, 212, 213, 214, 220), "ac_meter"),
    **dict.fromkeys((401, 402, 403, 404), "string_combiner"),
    501: "solar_module",
    803: "lithium_ion_bank",
}
