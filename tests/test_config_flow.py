"""Test SunSpec config flow."""
from unittest.mock import patch

import pytest
from custom_components.sunspec.const import CONF_ENABLED_MODELS
from custom_components.sunspec.const import DOMAIN
from homeassistant import config_entries
from homeassistant import data_entry_flow
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import MockSunSpecDataUpdateCoordinator
from .const import MOCK_CONFIG
from .const import MOCK_CONFIG_STEP_1
from .const import MOCK_SETTINGS


# This fixture bypasses the actual setup of the integration
# since we only want to test the config flow. We test the
# actual functionality of the integration in other test modules.
@pytest.fixture(autouse=True)
def bypass_setup_fixture():
    """Prevent setup."""
    with patch("custom_components.sunspec.async_setup", return_value=True,), patch(
        "custom_components.sunspec.async_setup_entry",
        return_value=True,
    ):
        yield


# Here we simiulate a successful config flow from the backend.
# Note that we use the `bypass_get_data` fixture here because
# we want the config flow validation to succeed during the test.
async def test_successful_config_flow(
    hass, bypass_get_data, enable_custom_integrations, sunspec_client_mock
):
    """Test a successful config flow."""
    # Initialize a config flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Check that the config flow shows the user form as the first step
    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "user"

    flow_id = result["flow_id"]
    # If a user were to enter `test_username` for username and `test_password`
    # for password, it would result in this function call
    result = await hass.config_entries.flow.async_configure(
        flow_id, user_input=MOCK_CONFIG_STEP_1
    )

    # Check that the config flow is complete and a new entry is created with
    # the input data
    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM

    result = await hass.config_entries.flow.async_configure(
        flow_id, user_input=MOCK_SETTINGS
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
    assert result["title"] == "test_host:123"
    assert result["data"] == MOCK_CONFIG
    assert result["result"]


# In this case, we want to simulate a failure during the config flow.
# We use the `error_on_get_data` mock instead of `bypass_get_data`
# (note the function parameters) to raise an Exception during
# validation of the input config.
async def test_failed_config_flow(
    hass, error_on_get_data, error_on_get_device_info, sunspec_client_mock
):
    """Test a failed config flow due to credential validation failure."""

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG_STEP_1
    )

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["errors"] == {"base": "connection"}


# Our config flow also has an options flow, so we must test it as well.
async def test_options_flow(hass, sunspec_client_mock):
    """Test an options flow."""
    # Create a new MockConfigEntry and add to HASS (we're bypassing config
    # flow entirely)
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG, entry_id="test")
    entry.add_to_hass(hass)

    coordinator = MockSunSpecDataUpdateCoordinator(hass, [1, 2])
    # api = SunSpecApiClient(host="test", port=123, slave_id=1, hass=hass)
    hass.data[DOMAIN] = {entry.entry_id: coordinator}

    # Initialize an options flow
    # await hass.config_entries.async_setup(entry.entry_id)
    result = await hass.config_entries.options.async_init(entry.entry_id)

    # Verify that the first options step is a user form
    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "model_options"

    # Enter some fake data into the form
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_ENABLED_MODELS: []}
    )

    # Verify that the flow finishes
    assert result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
    assert result["title"] == ""

    # Verify that the options were updated
    # assert entry.options == {BINARY_SENSOR: True, SENSOR: False, SWITCH: True}
