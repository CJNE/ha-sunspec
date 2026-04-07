"""Tests for SunSpec api."""

import pytest
from sunspec2.modbus.client import SunSpecModbusClientError
from sunspec2.modbus.client import SunSpecModbusClientException
from sunspec2.modbus.client import SunSpecModbusClientTimeout
from sunspec2.modbus.modbus import ModbusClientError

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
    """Test API calls."""

    # To test the api submodule, we first create an instance of our API client
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    with pytest.raises(Exception):
        api.modbus_connect()


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


async def test_modbus_connect_scan_error_surfaces_message(hass, mocker):
    """SunSpec scan failures must surface their message in ConnectionError.

    Regression test for issue #346 where client.scan() raised
    SunSpecModbusClientError but it was not caught by the except block in
    modbus_connect, leaking through as a generic Exception with message
    "Unexpected error while connecting" and no actionable details.
    """
    mocker.patch(
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.connect",
        return_value=None,
    )
    mocker.patch(
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.is_connected",
        return_value=True,
    )
    mocker.patch(
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.scan",
        side_effect=SunSpecModbusClientError("data time out"),
    )
    mocker.patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
    )

    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    with pytest.raises(ConnectionError) as excinfo:
        api.modbus_connect()
    # The original sunspec2 message must be preserved so users get something
    # actionable instead of a generic "Unexpected error".
    assert "data time out" in str(excinfo.value)


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
