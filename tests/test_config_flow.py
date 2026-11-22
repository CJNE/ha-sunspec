"""Test SunSpec config flow."""

import socket
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.data_entry_flow import InvalidData
import homeassistant.helpers.config_validation as cv
import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.sunspec import config_flow
from custom_components.sunspec.api import ConnectionTimeoutError
from custom_components.sunspec.api import NoSunSpecError
from custom_components.sunspec.api import SunSpecApiClient
from custom_components.sunspec.const import CONF_ALLOW_WRITING
from custom_components.sunspec.const import CONF_BAUDRATE
from custom_components.sunspec.const import CONF_DEVICE
from custom_components.sunspec.const import CONF_ENABLED_MODELS
from custom_components.sunspec.const import CONF_MODEL_INTERVALS
from custom_components.sunspec.const import CONF_PORT
from custom_components.sunspec.const import CONF_PREFIX
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
    # The connection closes in an executor job that runs as a background task.
    await hass.async_block_till_done(wait_background_tasks=True)

    assert disconnect.called is closed


@pytest.mark.parametrize(
    ("data", "title", "connection", "user_input", "device", "new_title"),
    [
        (
            MOCK_CONFIG,
            "test_host:123:1",
            "serial",
            MOCK_SERIAL_STEP_1,
            "/dev/ttyUSB0",
            "/dev/ttyUSB0:1",
        ),
        (
            MOCK_SERIAL_CONFIG,
            "/dev/ttyUSB0:1",
            "tcp",
            MOCK_CONFIG_STEP_1,
            None,
            "test_host:123:1",
        ),
        # A title the user gave the entry stays, whether it moves or not.
        (
            MOCK_CONFIG,
            "Roof inverter",
            "serial",
            MOCK_SERIAL_STEP_1,
            "/dev/ttyUSB0",
            "Roof inverter",
        ),
        (
            MOCK_CONFIG,
            "Roof inverter",
            "tcp",
            MOCK_CONFIG_STEP_1,
            None,
            "Roof inverter",
        ),
        # An entry not set up since its unit ID was slave_id, such as a
        # disabled one, keeps its title.
        (
            {"host": "test_host", "port": 123, "slave_id": 1},
            "test_host:123:1",
            "serial",
            MOCK_SERIAL_STEP_1,
            "/dev/ttyUSB0",
            "test_host:123:1",
        ),
    ],
)
async def test_config_flow_moves_device(
    hass, sunspec_client_mock, data, title, connection, user_input, device, new_title
):
    """Test that adding a configured device again moves it to the new connection."""
    entry = MockConfigEntry(
        domain=DOMAIN, data=data, title=title, unique_id="sn-123456789"
    )
    entry.add_to_hass(hass)

    result = await start_flow(hass, connection)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=user_input
    )

    assert result["type"] == FlowResultType.ABORT
    assert entry.data[CONF_DEVICE] == device
    assert entry.title == new_title


async def test_config_flow_ignored_device(hass, sunspec_client_mock):
    """Test that setup goes on for an ignored device and keeps its entry's title."""
    # Home Assistant fills in the connection of an ignored entry that a setup
    # passed, and its title can name that connection.
    entry = MockConfigEntry(
        domain=DOMAIN,
        source=config_entries.SOURCE_IGNORE,
        data=MOCK_SERIAL_CONFIG,
        title="/dev/ttyUSB0:1",
        unique_id="sn-123456789",
    )
    entry.add_to_hass(hass)

    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG_STEP_1
    )

    assert result["step_id"] == "settings"
    assert entry.title == "/dev/ttyUSB0:1"


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


@pytest.mark.parametrize("step_id", ["tcp", "reconfigure"])
@pytest.mark.parametrize(
    ("error", "base"),
    [(ConnectionTimeoutError, "timeout"), (NoSunSpecError, "no_sunspec")],
)
async def test_config_flow_error(hass, sunspec_client_mock, step_id, error, base):
    """Test that setup and Reconfigure name why they cannot read the device."""
    if step_id == "reconfigure":
        entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
        entry.add_to_hass(hass)
        result = await entry.start_reconfigure_flow(hass)
    else:
        result = await start_flow(hass)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == step_id

    with patch(
        "custom_components.sunspec.SunSpecApiClient.async_get_device_info",
        side_effect=error,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=MOCK_CONFIG_STEP_1
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == step_id
    assert result["errors"] == {"base": base}


async def test_config_flow_unknown_host(hass, mocker):
    """Test that setup reports a host name that does not resolve as no connection."""
    sock = mocker.patch("custom_components.sunspec.api.socket.socket").return_value
    sock.connect_ex.side_effect = socket.gaierror(
        socket.EAI_NONAME, "Name or service not known"
    )
    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG_STEP_1
    )

    assert result["errors"] == {"base": "connection"}


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
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={CONF_ENABLED_MODELS: [], CONF_SCAN_INTERVAL: scan_interval},
        )


@pytest.mark.parametrize("step_id", ["tcp", "reconfigure"])
@pytest.mark.parametrize("port", [0, 65536])
async def test_port_in_range(hass, sunspec_client_mock, step_id, port):
    """Test that setup and Reconfigure refuse a port outside 1 to 65535."""
    if step_id == "reconfigure":
        entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
        entry.add_to_hass(hass)
        result = await entry.start_reconfigure_flow(hass)
    else:
        result = await start_flow(hass)

    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={**MOCK_CONFIG_STEP_1, CONF_PORT: port}
        )


async def test_fields_left_out(hass, bypass_get_data, sunspec_client_mock):
    """Test that setup and Configure take the values an entry runs with for fields left out."""
    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG_STEP_1
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_ENABLED_MODELS: [103]}
    )
    assert result["data"][CONF_SCAN_INTERVAL] == 30

    # An entry from before the prefix and the scan interval were settings.
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG_STEP_1, entry_id="old")
    entry.add_to_hass(hass)
    coordinator = MockSunSpecDataUpdateCoordinator(hass, [1])
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_ENABLED_MODELS: []}
    )
    assert entry.options[CONF_PREFIX] == ""
    assert entry.options[CONF_SCAN_INTERVAL] == 30


@pytest.mark.parametrize(
    ("form", "fields"),
    [
        ("tcp", {CONF_PORT, CONF_UNIT_ID}),
        ("serial", {CONF_BAUDRATE, CONF_UNIT_ID}),
        ("reconfigure", {CONF_PORT, CONF_UNIT_ID}),
    ],
)
async def test_number_fields(hass, sunspec_client_mock, form, fields):
    """Test that the number fields are number boxes, which ask for a number."""
    if form == "reconfigure":
        entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
        entry.add_to_hass(hass)
        result = await entry.start_reconfigure_flow(hass)
    else:
        result = await start_flow(hass, form)

    # Serialized as Home Assistant sends the form to the frontend: with
    # probatio since 2026.9, with voluptuous-serialize before.
    try:
        from probatio import to_field_list as serialize
    except ImportError:
        from voluptuous_serialize import convert as serialize
    schema = serialize(result["data_schema"], custom_serializer=cv.custom_serializer)
    boxes = {
        field["name"]
        for field in schema
        if field.get("selector", {}).get("number", {}).get("mode") == "box"
    }
    assert boxes == fields


@pytest.mark.parametrize(
    ("data", "title", "user_input", "new_title"),
    [
        # A title that names the connection follows it.
        (
            MOCK_CONFIG,
            "test_host:123:1",
            {**MOCK_CONFIG_STEP_1, CONF_PORT: 502},
            "test_host:502:1",
        ),
        (
            {**MOCK_CONFIG, CONF_UNIT_ID: 0},
            "test_host:123:0",
            {**MOCK_CONFIG_STEP_1, CONF_UNIT_ID: 0},
            "test_host:123:0",
        ),
        (
            MOCK_SERIAL_CONFIG,
            "/dev/ttyUSB0:1",
            {**MOCK_SERIAL_STEP_1, CONF_BAUDRATE: 19200},
            "/dev/ttyUSB0:1",
        ),
        # A title the user gave stays.
        (
            MOCK_CONFIG,
            "Roof inverter",
            {**MOCK_CONFIG_STEP_1, CONF_PORT: 502},
            "Roof inverter",
        ),
        # An entry not set up since its unit ID was slave_id, such as a
        # disabled one, shows that unit ID and keeps its title.
        (
            {"host": "test_host", "port": 123, "slave_id": 7},
            "test_host:123:7",
            {**MOCK_CONFIG_STEP_1, CONF_PORT: 502, CONF_UNIT_ID: 7},
            "test_host:123:7",
        ),
    ],
)
async def test_reconfigure_flow(
    hass, sunspec_client_mock, mocker, data, title, user_input, new_title
):
    """Test that Reconfigure moves an entry to a new connection to its device."""
    reload = mocker.patch.object(hass.config_entries, "async_schedule_reload")
    entry = MockConfigEntry(
        domain=DOMAIN, data=data, title=title, unique_id="sn-123456789"
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)

    assert result["step_id"] == "reconfigure"
    # It shows the entry's unit ID, which each row keeps.
    unit_id = next(key for key in result["data_schema"].schema if key == CONF_UNIT_ID)
    assert unit_id.default() == user_input[CONF_UNIT_ID]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=user_input
    )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    reload.assert_called_once_with(entry.entry_id)
    # The entry keeps the settings chosen at setup, and no entry is added.
    assert entry.data == {**data, **user_input}
    assert entry.title == new_title
    assert hass.config_entries.async_entries(DOMAIN) == [entry]


@pytest.mark.parametrize(
    ("unique_id", "serial_number", "reason"),
    [
        ("sn-123456789", True, "reconfigure_successful"),
        ("sn-555", True, "unique_id_mismatch"),
        # A device without a serial number cannot be told apart, and an entry
        # without a unique ID has none to compare.
        ("test_host:123:1", False, "reconfigure_successful"),
        (None, True, "reconfigure_successful"),
    ],
)
async def test_reconfigure_same_device(
    hass,
    sunspec_client_mock,
    device_info_without_serial,
    mocker,
    unique_id,
    serial_number,
    reason,
):
    """Test that Reconfigure keeps an entry on its own device."""
    if not serial_number:
        mocker.patch.object(
            SunSpecApiClient,
            "async_get_device_info",
            return_value=device_info_without_serial,
        )
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG, unique_id=unique_id)
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={**MOCK_CONFIG_STEP_1, CONF_PORT: 502}
    )
    await hass.async_block_till_done()

    assert result["reason"] == reason
    assert entry.data[CONF_PORT] == (502 if reason == "reconfigure_successful" else 123)
    assert entry.unique_id == unique_id


# Our config flow also has an options flow, so we must test it as well.
async def test_options_flow(hass, sunspec_client_mock):
    """Test that Configure opens on the models, without the connection."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG, entry_id="test")
    entry.add_to_hass(hass)
    hass.data[DOMAIN] = {entry.entry_id: MockSunSpecDataUpdateCoordinator(hass, [1])}

    result = await hass.config_entries.options.async_init(entry.entry_id)

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
    assert models.default() == set(MOCK_CONFIG[CONF_ENABLED_MODELS])

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_ENABLED_MODELS: [],
            CONF_SCAN_INTERVAL: 10,
            CONF_MODEL_INTERVALS: {"103": 5},
            CONF_ALLOW_WRITING: True,
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == ""
    assert entry.options[CONF_MODEL_INTERVALS] == {"103": 5}
    assert entry.options[CONF_ALLOW_WRITING] is True


async def test_options_flow_clears_prefix(hass, sunspec_client_mock):
    """Test that Configure shows the prefix and drops it when the field is emptied."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG,
        options={**MOCK_SETTINGS, CONF_PREFIX: "SE7600"},
        entry_id="test",
    )
    entry.add_to_hass(hass)
    hass.data[DOMAIN] = {entry.entry_id: MockSunSpecDataUpdateCoordinator(hass, [1])}
    result = await hass.config_entries.options.async_init(entry.entry_id)
    prefix = next(key for key in result["data_schema"].schema if key == CONF_PREFIX)
    assert prefix.description == {"suggested_value": "SE7600"}

    # The form leaves an emptied field out.
    await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_ENABLED_MODELS: []}
    )

    assert entry.options[CONF_PREFIX] == ""


async def test_options_flow_connect_error(hass, sunspec_client_mock_connect_error):
    """Test that Configure says why it cannot read the device's models."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG, entry_id="test")
    entry.add_to_hass(hass)
    hass.data[DOMAIN] = {entry.entry_id: MockSunSpecDataUpdateCoordinator(hass, [1])}

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "connection"
