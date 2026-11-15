"""Tests for SunSpec api."""

import struct

from modbus_connection import IllegalDataAddressError
from modbus_connection import ModbusConnectionError
from modbus_connection import ModbusSerialParams
from modbus_connection import ModbusTcpParams
from modbus_connection import ModbusTimeoutError
import pytest
from sunspec2.device import ModelError
from sunspec2.modbus.client import SunSpecModbusClientError

from custom_components.sunspec.api import SERIAL_TIMEOUT
from custom_components.sunspec.api import TIMEOUT
from custom_components.sunspec.api import ConnectionError
from custom_components.sunspec.api import ConnectionTimeoutError
from custom_components.sunspec.api import NoSunSpecError
from custom_components.sunspec.api import SunSpecApiClient
from custom_components.sunspec.api import modbus_link
from scripts.simulator import load_registers

from . import create_mock_sunspec_client
from .const import MOCK_CONFIG
from .const import MOCK_SERIAL_CONFIG


async def test_api(hass, sunspec_client_mock):
    """Test API calls."""

    # To test the api submodule, we first create an instance of our API client
    api = create_mock_sunspec_client(hass)

    models = await api.async_get_models()
    assert models == [
        1,
        103,
        160,
        304,
        701,
        702,
        703,
        704,
        705,
        706,
        707,
        708,
        709,
        710,
        711,
        712,
    ]

    device_info = await api.async_get_device_info()

    assert device_info.getValue("Mn") == "SunSpecTest"
    assert device_info.getValue("SN") == "sn-123456789"

    model = await api.async_get_data(701)
    assert model.getValue("W") == 9800
    assert model.getMeta("W")["label"] == "Active Power"

    model = await api.async_get_data(705)
    keys = model.getKeys()
    assert len(keys) == 22


async def test_reads_through_unit(hass, mocker, mock_modbus_unit):
    """Test that the scan and model reads go through the unit, in requests Modbus allows."""
    mocker.patch("custom_components.sunspec.api.socket.create_connection")
    mocker.patch("custom_components.sunspec.api.time.sleep")
    registers = load_registers("tests/test_data/inverter.json")
    mock_modbus_unit.holding[40000] = list(
        struct.unpack(f">{len(registers) // 2}H", registers)
    )
    api = SunSpecApiClient(hass, MOCK_CONFIG, mock_modbus_unit)

    assert await api.async_get_models() == [1, 103, 160, 304, *range(701, 713)]
    assert (await api.async_get_data(701)).getValue("W") == 9800

    # pysunspec2 reads a model it has no definition for in one piece.
    device = api.get_client()
    assert await hass.async_add_executor_job(device.read, 40000, 300) == registers[:600]
    assert [read.count for read in mock_modbus_unit.read_events[-3:]] == [125, 125, 50]


def model(model_id, length, values):
    """Return a model of the given length, zero apart from values by offset."""
    body = [0] * length
    for offset, value in values.items():
        body[offset] = value & 0xFFFF
    return model_id, body


@pytest.mark.parametrize(
    ("battery", "points"),
    [
        # An E3DC S10 serves 801 to 803 as defined in 2015 (#62).
        (
            [
                model(801, 22, {9: 55}),
                model(802, 20, {3: 500}),
                model(803, 32, {1: 3350, 12: -3}),
            ],
            {801: ("SoC", 55), 802: ("CycleCt", 500), 803: ("BMaxCellVol", 3.35)},
        ),
        (
            [model(802, 62, {9: 77}), model(803, 58, {0: 1})],
            {802: ("SoC", 77), 803: ("NStr", 1)},
        ),
    ],
)
async def test_battery_model_definitions(
    hass, mocker, mock_modbus_unit, battery, points
):
    """Test that 801 to 803 at their 2015 lengths are read with the 2015 definitions."""
    registers = [0x5375, 0x6E53]
    for model_id, body in [model(1, 66, {}), *battery, model(103, 50, {})]:
        registers += [model_id, len(body), *body]
    mock_modbus_unit.holding[40000] = [*registers, 0xFFFF, 0]
    mocker.patch("custom_components.sunspec.api.socket.create_connection")
    mocker.patch("custom_components.sunspec.api.time.sleep")
    api = SunSpecApiClient(hass, MOCK_CONFIG, mock_modbus_unit)

    assert await api.async_get_models() == sorted([1, 103, *points])
    for model_id, (point, value) in points.items():
        assert (await api.async_get_data(model_id)).getValue(point) == value


@pytest.mark.parametrize(
    ("data", "params", "timeout"),
    [
        (MOCK_CONFIG, ModbusTcpParams(host="test_host", port=123), TIMEOUT),
        (
            MOCK_SERIAL_CONFIG,
            ModbusSerialParams(device="/dev/ttyUSB0", baudrate=9600, parity="N"),
            SERIAL_TIMEOUT,
        ),
    ],
)
async def test_connection_settings(hass, mock_modbus_unit, data, params, timeout):
    """Test that an entry's settings give its link, unit ID and request timeout."""
    assert modbus_link(data) == (params, 1)

    SunSpecApiClient(hass, data, mock_modbus_unit)

    assert mock_modbus_unit.required_timeout == timeout


@pytest.mark.parametrize(
    ("data", "connected", "reachable", "scanned"),
    [
        (MOCK_CONFIG, False, False, False),
        (MOCK_CONFIG, False, True, True),
        (MOCK_CONFIG, True, False, True),
        (MOCK_SERIAL_CONFIG, False, False, True),
    ],
)
async def test_quick_connection_check(
    hass, mocker, data, connected, reachable, scanned
):
    """Test that a TCP device not yet connected gets one quick connection first."""
    check = mocker.patch(
        "custom_components.sunspec.api.socket.create_connection",
        side_effect=None if reachable else OSError("No route to host"),
    )
    sleep = mocker.patch("custom_components.sunspec.api.time.sleep")
    scan = mocker.patch("custom_components.sunspec.api.UnitDevice.scan")
    api = SunSpecApiClient(hass, data, mocker.Mock(connected=connected))

    if scanned:
        api.scan()
    else:
        with pytest.raises(ConnectionError):
            api.scan()

    assert scan.called is scanned
    assert check.called is (data is MOCK_CONFIG and not connected)
    # Some SolarEdge inverters reset a connection that follows another too
    # closely (#321).
    paused = mocker.call(0.1) in sleep.call_args_list
    assert paused == (check.called and reachable)


async def test_scan_once(hass, mocker):
    """Test that the device is scanned once, not at every read."""
    scan = mocker.patch("custom_components.sunspec.api.UnitDevice.scan")
    api = create_mock_sunspec_client(hass)

    api.get_client()
    api.get_client()

    scan.assert_called_once()


@pytest.mark.parametrize(
    "error",
    [
        IllegalDataAddressError(),
        ModelError("Repeating group count not consistent with model length"),
    ],
)
async def test_partial_scan(hass, mocker, error):
    """Test that a scan ended by an exception or a model it cannot parse keeps the models found."""

    def scan(self, **kwargs):
        self.models[1] = ["common"]
        raise error

    mocker.patch("custom_components.sunspec.api.UnitDevice.scan", scan)
    api = create_mock_sunspec_client(hass)

    assert api.scan().models == {1: ["common"]}


@pytest.mark.parametrize(
    ("error", "connected", "raised"),
    [
        (ModbusTimeoutError("Response timeout"), True, ConnectionTimeoutError),
        (ModbusConnectionError("Connection lost"), True, ConnectionError),
        (IllegalDataAddressError(), True, ConnectionError),
        (SunSpecModbusClientError("No SunSpec map"), True, NoSunSpecError),
        (SunSpecModbusClientError("No SunSpec map"), False, ConnectionError),
        (struct.error("'H' format requires 0 <= number <= 65535"), True, struct.error),
    ],
)
async def test_scan_error(hass, mocker, error, connected, raised):
    """Test that a failed scan says why: the connection, a timeout, or no SunSpec."""
    mocker.patch("custom_components.sunspec.api.socket.create_connection")
    mocker.patch("custom_components.sunspec.api.time.sleep")
    mocker.patch("custom_components.sunspec.api.UnitDevice.scan", side_effect=error)
    api = SunSpecApiClient(hass, MOCK_CONFIG, mocker.Mock(connected=connected))

    with pytest.raises(raised):
        api.scan()


@pytest.mark.parametrize(("manufacturer", "delay"), [("SMA", 1), ("Fronius", 0.6)])
async def test_read_model_delay(hass, mocker, manufacturer, delay):
    """Test that an SMA device gets a second before each model read."""
    sleep = mocker.patch("custom_components.sunspec.api.time.sleep")
    common = mocker.Mock(points={"Mn": mocker.Mock(value=manufacturer)})
    client = mocker.Mock(models={1: [common], 103: [mocker.Mock()]})
    mocker.patch(
        "custom_components.sunspec.api.SunSpecApiClient.scan", return_value=client
    )
    api = create_mock_sunspec_client(hass)

    api.read_model(103)

    sleep.assert_called_once_with(delay)


async def test_read_model_timeout(hass, mocker):
    mocker.patch(
        "custom_components.sunspec.api.SunSpecApiClient.read_model",
        side_effect=ModbusTimeoutError("timed out"),
    )
    api = create_mock_sunspec_client(hass)

    with pytest.raises(ConnectionTimeoutError):
        await api.async_get_data(1)


async def test_read_model_error(hass, mocker):
    mocker.patch(
        "custom_components.sunspec.api.SunSpecApiClient.read_model",
        side_effect=ModbusConnectionError("Connection lost"),
    )
    api = create_mock_sunspec_client(hass)

    with pytest.raises(ConnectionError):
        await api.async_get_data(1)
