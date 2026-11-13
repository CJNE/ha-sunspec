"""Tests for SunSpec api."""

import errno
import socket
import struct

import pytest
from sunspec2.device import ModelError
from sunspec2.modbus.client import SunSpecModbusClientException
from sunspec2.modbus.client import SunSpecModbusClientTimeout
from sunspec2.modbus.modbus import ModbusClientError
from sunspec2.modbus.modbus import ModbusClientException
from sunspec2.modbus.modbus import ModbusClientTimeout

from custom_components.sunspec.api import ConnectionError
from custom_components.sunspec.api import ConnectionTimeoutError
from custom_components.sunspec.api import SunSpecApiClient


async def test_api(hass, sunspec_client_mock):
    """Test API calls."""

    # To test the api submodule, we first create an instance of our API client
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

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


async def test_get_client(hass, sunspec_modbus_client_mock):
    SunSpecApiClient.CLIENT_CACHE = {}
    """Test API calls."""

    # To test the api submodule, we first create an instance of our API client
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)
    client = api.get_client()
    client.scan.assert_called_once()

    SunSpecApiClient.CLIENT_CACHE = {}


async def test_modbus_connect(hass, sunspec_modbus_client_mock):
    SunSpecApiClient.CLIENT_CACHE = {}
    """Test API calls."""

    # To test the api submodule, we first create an instance of our API client
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)
    SunSpecApiClient.CLIENT_CACHE = {}
    client = api.get_client()
    client.scan.assert_called_once()

    SunSpecApiClient.CLIENT_CACHE = {}


async def test_modbus_connect_fail(hass, mocker):
    mocker.patch(
        # api_call is from slow.py but imported to main.py
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.connect",
        return_value={},
    )
    mocker.patch(
        # api_call is from slow.py but imported to main.py
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.is_connected",
        return_value=False,
    )
    mocker.patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
    )
    """Test API calls."""

    # To test the api submodule, we first create an instance of our API client
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    with pytest.raises(ConnectionError):
        api.modbus_connect()


@pytest.mark.parametrize(
    ("connect_result", "is_open"), [(0, True), (errno.ECONNREFUSED, False)]
)
async def test_check_port(hass, mocker, connect_result, is_open):
    sock = mocker.patch("custom_components.sunspec.api.socket.socket").return_value
    sock.connect_ex.return_value = connect_result
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    assert api.check_port() is is_open
    sock.settimeout.assert_called_once_with(3)
    assert socket.getdefaulttimeout() is None


@pytest.mark.parametrize(
    "error",
    [
        ModbusClientException("Modbus exception 2"),
        ModelError("Repeating group count not consistent with model length"),
    ],
)
async def test_modbus_connect_partial_scan(hass, mocker, error):
    """Test that a scan ended by an exception or a model it cannot parse keeps the models found."""

    def scan(self, **kwargs):
        self.models[1] = ["common"]
        raise error

    mocker.patch("sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.connect")
    mocker.patch(
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.is_connected",
        return_value=True,
    )
    mocker.patch("sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.scan", scan)
    mocker.patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
    )
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    assert api.modbus_connect().models == {1: ["common"]}


@pytest.mark.parametrize("closed", [True, False])
async def test_read_model_reconnects_closed_connection(hass, mocker, closed):
    """Test that a connection the device closed is reopened before reading."""
    sock, device_end = socket.socketpair()
    if closed:
        device_end.close()
    client = mocker.Mock(models={1: []})
    client.client.socket = sock
    SunSpecApiClient.CLIENT_CACHE["test:123:1"] = client
    mocker.patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
    )
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    api.read_model(1)

    assert client.connect.called is closed
    sock.close()
    device_end.close()


@pytest.mark.parametrize(
    ("error", "raised"),
    [
        (ModbusClientTimeout("Response timeout"), ConnectionError),
        (struct.error("'H' format requires 0 <= number <= 65535"), struct.error),
    ],
)
async def test_modbus_connect_failed_scan_closes(hass, mocker, error, raised):
    """Test that a failed scan closes its connection."""
    mocker.patch("sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.connect")
    mocker.patch(
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.is_connected",
        return_value=True,
    )
    mocker.patch(
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.scan", side_effect=error
    )
    disconnect = mocker.patch(
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.disconnect"
    )
    mocker.patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
    )
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    with pytest.raises(raised):
        api.modbus_connect()

    disconnect.assert_called_once()


async def test_modbus_connect_exception(hass, mocker):
    mocker.patch(
        # api_call is from slow.py but imported to main.py
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.connect",
        side_effect=ModbusClientError,
    )
    mocker.patch(
        # api_call is from slow.py but imported to main.py
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.is_connected",
        return_value=False,
    )
    mocker.patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
    )
    """Test API calls."""

    # To test the api submodule, we first create an instance of our API client
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    with pytest.raises(ConnectionError):
        api.modbus_connect()


@pytest.mark.parametrize(("manufacturer", "delay"), [("SMA", 1), ("Fronius", 0.6)])
async def test_read_model_delay(hass, mocker, manufacturer, delay):
    """Test that an SMA device gets a second before each model read."""
    sleep = mocker.patch("custom_components.sunspec.api.time.sleep")
    common = mocker.Mock(points={"Mn": mocker.Mock(value=manufacturer)})
    client = mocker.Mock(models={1: [common], 103: [mocker.Mock()]})
    client.client.socket = None
    SunSpecApiClient.CLIENT_CACHE["test:123:1"] = client
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    api.read_model(103)

    sleep.assert_called_once_with(delay)


async def test_read_model_timeout(hass, mocker):
    mocker.patch(
        "custom_components.sunspec.api.SunSpecApiClient.read_model",
        side_effect=SunSpecModbusClientTimeout,
    )
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    with pytest.raises(ConnectionTimeoutError):
        await api.async_get_data(1)


async def test_read_model_error(hass, mocker):
    mocker.patch(
        "custom_components.sunspec.api.SunSpecApiClient.read_model",
        side_effect=SunSpecModbusClientException,
    )
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    with pytest.raises(ConnectionError):
        await api.async_get_data(1)
