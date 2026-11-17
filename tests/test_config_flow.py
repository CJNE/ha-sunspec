"""Test SunSpec config flow."""

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.data_entry_flow import InvalidData
import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.sunspec import config_flow
from custom_components.sunspec.api import ConnectionTimeoutError
from custom_components.sunspec.api import NoSunSpecError
from custom_components.sunspec.api import SunSpecApiClient
from custom_components.sunspec.const import CONF_ALLOW_WRITING
from custom_components.sunspec.const import CONF_DEVICE
from custom_components.sunspec.const import CONF_ENABLED_MODELS
from custom_components.sunspec.const import CONF_MODEL_INTERVALS
from custom_components.sunspec.const import CONF_SCAN_INTERVAL
from custom_components.sunspec.const import CONF_UNIT_ID
from custom_components.sunspec.const import DOMAIN

from . import MockSunSpecDataUpdateCoordinator
from .const import MOCK_CONFIG
from .const import MOCK_CONFIG_STEP_1
from .const import MOCK_SERIAL_CONFIG
from .const import MOCK_SERIAL_STEP_1
from .const import MOCK_SETTINGS


# This fixture bypasses the actual setup of the integration
# since we only want to test the config flow. We test the
# actual functionality of the integration in other test modules.
@pytest.fixture(autouse=True)
def bypass_setup_fixture():
    """Prevent setup."""
    with patch(
        "custom_components.sunspec.async_setup_entry",
        return_value=True,
    ):
        yield


async def start_flow(hass, connection="tcp"):
    """Start a config flow and choose how the device is connected."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": connection}
    )


# Here we simiulate a successful config flow from the backend.
# Note that we use the `bypass_get_data` fixture here because
# we want the config flow validation to succeed during the test.
@pytest.mark.parametrize(
    ("connection", "user_input", "title", "data"),
    [
        ("tcp", MOCK_CONFIG_STEP_1, "test_host:123:1", MOCK_CONFIG),
        (
            "tcp",
            {**MOCK_CONFIG_STEP_1, CONF_UNIT_ID: 0},
            "test_host:123:0",
            {**MOCK_CONFIG, CONF_UNIT_ID: 0},
        ),
        ("serial", MOCK_SERIAL_STEP_1, "/dev/ttyUSB0:1", MOCK_SERIAL_CONFIG),
    ],
)
async def test_successful_config_flow(
    hass,
    bypass_get_data,
    enable_custom_integrations,
    sunspec_client_mock,
    mocker,
    connection,
    user_input,
    title,
    data,
):
    """Test a successful config flow."""
    api_client = mocker.spy(config_flow, "api_client")
    result = await start_flow(hass, connection)

    # Check that the config flow shows the connection form
    assert result["type"] == "form"
    assert result["step_id"] == connection

    flow_id = result["flow_id"]
    result = await hass.config_entries.flow.async_configure(
        flow_id, user_input=user_input
    )

    # The device was read at the unit ID entered.
    assert api_client.call_args.args[1][CONF_UNIT_ID] == user_input[CONF_UNIT_ID]

    # Check that the config flow is complete and a new entry is created with
    # the input data
    assert result["type"] == FlowResultType.FORM
    assert list(dict(result["data_schema"].schema)[CONF_ENABLED_MODELS].options) == [
        1,
        103,
        160,
        304,
        *range(701, 713),
    ]

    result = await hass.config_entries.flow.async_configure(
        flow_id, user_input=MOCK_SETTINGS
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == title
    assert result["data"] == data
    assert result["result"]


@pytest.mark.parametrize(
    ("models", "ticked"), [([1, 213], {213}), ([1, 203, 213], {203})]
)
async def test_config_flow_ticks_float_models(
    hass, sunspec_client_mock, mocker, models, ticked
):
    """Test that setup ticks a float model for a device without its integer one."""
    mocker.patch.object(SunSpecApiClient, "async_get_models", return_value=models)
    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG_STEP_1
    )

    enabled = next(
        key for key in result["data_schema"].schema if key == CONF_ENABLED_MODELS
    )
    assert enabled.default() == ticked


@pytest.mark.parametrize(("finish", "closed"), [(True, False), (False, True)])
async def test_config_flow_connection(
    hass, sunspec_client_mock, mocker, finish, closed
):
    """Test that setup leaves its connection to the entry, and closes it otherwise."""
    disconnect = mocker.spy(SunSpecApiClient.modbus_connect.return_value, "disconnect")
    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG_STEP_1
    )

    if finish:
        await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=MOCK_SETTINGS
        )
    else:
        # The dialog is closed.
        hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()

    assert disconnect.called is closed


@pytest.mark.parametrize(
    ("data", "connection", "user_input", "device"),
    [
        (MOCK_CONFIG, "serial", MOCK_SERIAL_STEP_1, "/dev/ttyUSB0"),
        (MOCK_SERIAL_CONFIG, "tcp", MOCK_CONFIG_STEP_1, None),
    ],
)
async def test_config_flow_moves_device(
    hass, sunspec_client_mock, data, connection, user_input, device
):
    """Test that adding a configured device again moves it to the new connection."""
    entry = MockConfigEntry(domain=DOMAIN, data=data, unique_id="sn-123456789")
    entry.add_to_hass(hass)

    result = await start_flow(hass, connection)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=user_input
    )

    assert result["type"] == FlowResultType.ABORT
    assert entry.data[CONF_DEVICE] == device


# In this case, we want to simulate a failure during the config flow.
# We use the `error_on_get_data` mock instead of `bypass_get_data`
# (note the function parameters) to raise an Exception during
# validation of the input config.
async def test_failed_config_flow(
    hass, error_on_get_data, error_on_get_device_info, sunspec_client_mock
):
    """Test a failed config flow due to credential validation failure."""

    result = await start_flow(hass)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "tcp"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG_STEP_1
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "device_error"}


@pytest.mark.parametrize(
    ("error", "base"),
    [(ConnectionTimeoutError, "timeout"), (NoSunSpecError, "no_sunspec")],
)
async def test_config_flow_error(hass, sunspec_client_mock, error, base):
    """Test that setup names why it cannot read the device."""

    result = await start_flow(hass)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "tcp"

    with patch(
        "custom_components.sunspec.SunSpecApiClient.async_get_device_info",
        side_effect=error,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=MOCK_CONFIG_STEP_1
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": base}


async def test_config_flow_without_serial_number(
    hass, device_info_without_serial, sunspec_client_mock
):
    """Test config flow falls back when the device does not expose SN."""
    with patch(
        "custom_components.sunspec.SunSpecApiClient.async_get_device_info",
        return_value=device_info_without_serial,
    ):
        result = await start_flow(hass)

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "tcp"

        flow_id = result["flow_id"]
        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input=MOCK_CONFIG_STEP_1
        )

        assert result["type"] == FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(
            flow_id, user_input=MOCK_SETTINGS
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "test_host:123:1"


@pytest.mark.parametrize("scan_interval", [0, -5])
async def test_scan_interval_at_least_one(hass, sunspec_client_mock, scan_interval):
    """Test that setup and Configure refuse a scan interval below one second."""
    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG_STEP_1
    )
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={**MOCK_SETTINGS, CONF_SCAN_INTERVAL: scan_interval},
        )

    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG, entry_id="test")
    entry.add_to_hass(hass)
    hass.data[DOMAIN] = {entry.entry_id: MockSunSpecDataUpdateCoordinator(hass, [1])}
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG_STEP_1
    )
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={CONF_ENABLED_MODELS: [], CONF_SCAN_INTERVAL: scan_interval},
        )


# Our config flow also has an options flow, so we must test it as well.
@pytest.mark.parametrize(
    ("data", "step_id", "user_input", "title"),
    [
        (MOCK_CONFIG, "host_options", MOCK_CONFIG_STEP_1, "test_host:123:1"),
        (
            {**MOCK_CONFIG, CONF_UNIT_ID: 0},
            "host_options",
            {**MOCK_CONFIG_STEP_1, CONF_UNIT_ID: 0},
            "test_host:123:0",
        ),
        (MOCK_SERIAL_CONFIG, "serial_options", MOCK_SERIAL_STEP_1, "/dev/ttyUSB0:1"),
    ],
)
async def test_options_flow(
    hass, sunspec_client_mock, data, step_id, user_input, title
):
    """Test an options flow."""
    # Create a new MockConfigEntry and add to HASS (we're bypassing config
    # flow entirely)
    entry = MockConfigEntry(domain=DOMAIN, data=data, entry_id="test")
    entry.add_to_hass(hass)

    coordinator = MockSunSpecDataUpdateCoordinator(hass, [1, 2])
    hass.data[DOMAIN] = {entry.entry_id: coordinator}

    # Initialize an options flow
    result = await hass.config_entries.options.async_init(entry.entry_id)

    # Verify that the first options step is a user form
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == step_id
    # It shows the entry's unit ID.
    unit_id = next(key for key in result["data_schema"].schema if key == CONF_UNIT_ID)
    assert unit_id.default() == data[CONF_UNIT_ID]

    # Enter some fake data into the form
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=user_input
    )

    # Verify that the second options step is a user form
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "model_options"
    assert list(dict(result["data_schema"].schema)[CONF_ENABLED_MODELS].options) == [
        1,
        103,
        160,
        304,
        *range(701, 713),
    ]
    # The models chosen at setup are ticked, not the default ones.
    models = next(
        key for key in result["data_schema"].schema if key == CONF_ENABLED_MODELS
    )
    assert models.default() == set(data[CONF_ENABLED_MODELS])

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_ENABLED_MODELS: [],
            CONF_SCAN_INTERVAL: 10,
            CONF_MODEL_INTERVALS: {"103": 5},
            CONF_ALLOW_WRITING: True,
        },
    )

    # Verify that the flow finishes
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == ""
    assert entry.title == title
    assert entry.options[CONF_MODEL_INTERVALS] == {"103": 5}
    assert entry.options[CONF_ALLOW_WRITING] is True


# Test faild connection in options flow
async def test_options_flow_connect_error(hass, sunspec_client_mock_connect_error):
    """Test an options flow."""
    # Create a new MockConfigEntry and add to HASS (we're bypassing config
    # flow entirely)
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG, entry_id="test")
    entry.add_to_hass(hass)

    coordinator = MockSunSpecDataUpdateCoordinator(hass, [1, 2])
    hass.data[DOMAIN] = {entry.entry_id: coordinator}

    # Initialize an options flow
    result = await hass.config_entries.options.async_init(entry.entry_id)

    # Verify that the first options step is a user form
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "host_options"

    # Enter some fake data into the form
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG_STEP_1
    )

    # Verify that we return to host settings
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "host_options"
    assert result["errors"] == {"base": "connection"}
