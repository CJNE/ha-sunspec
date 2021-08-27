"""Tests for SunSpec api."""
import pytest
from custom_components.sunspec.api import (
    SunSpecApiClient,
)


async def test_api(hass, sunspec_client_mock):
    """Test API calls."""

    # To test the api submodule, we first create an instance of our API client
    api = SunSpecApiClient(host="test", port=123, slave_id=1, hass=hass)

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


async def test_modbus_connect(hass, sunspec_modbus_client_mock):
    SunSpecApiClient.CLIENT_CACHE = {}
    """Test API calls."""

    # To test the api submodule, we first create an instance of our API client
    api = SunSpecApiClient(host="test", port=123, slave_id=1, hass=hass)
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
    api = SunSpecApiClient(host="test", port=123, slave_id=1, hass=hass)

    with pytest.raises(Exception):
        api.modbus_connect()
