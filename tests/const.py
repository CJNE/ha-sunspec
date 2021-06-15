"""Constants for SunSpec tests."""
from custom_components.sunspec.const import CONF_ENABLED_MODELS
from custom_components.sunspec.const import CONF_HOST
from custom_components.sunspec.const import CONF_PORT
from custom_components.sunspec.const import CONF_PREFIX
from custom_components.sunspec.const import CONF_SLAVE_ID

MOCK_SETTINGS_PREFIX = {CONF_ENABLED_MODELS: ["160"], CONF_PREFIX: "test"}
MOCK_SETTINGS = {CONF_ENABLED_MODELS: ["103", "160"]}
MOCK_SETTINGS_MM = {CONF_ENABLED_MODELS: ["701"]}
MOCK_CONFIG_STEP_1 = {CONF_HOST: "test_host", CONF_PORT: 123, CONF_SLAVE_ID: 1}
MOCK_CONFIG = {
    CONF_HOST: "test_host",
    CONF_PORT: 123,
    CONF_SLAVE_ID: 1,
    CONF_PREFIX: "",
    CONF_ENABLED_MODELS: MOCK_SETTINGS[CONF_ENABLED_MODELS],
}
MOCK_CONFIG_MM = {
    CONF_HOST: "test_host",
    CONF_PORT: 123,
    CONF_SLAVE_ID: 1,
    CONF_PREFIX: "",
    CONF_ENABLED_MODELS: MOCK_SETTINGS_MM[CONF_ENABLED_MODELS],
}
MOCK_CONFIG_PREFIX = {
    CONF_HOST: "test_host",
    CONF_PORT: 123,
    CONF_SLAVE_ID: 1,
    CONF_PREFIX: "test",
    CONF_ENABLED_MODELS: MOCK_SETTINGS_PREFIX[CONF_ENABLED_MODELS],
}
