"""Global fixtures for SunSpec integration."""
from typing import Any
from unittest.mock import Mock
from unittest.mock import patch

import pytest
import sunspec2.file.client as modbus_client

pytest_plugins = "pytest_homeassistant_custom_component"


# This fixture is used to prevent HomeAssistant from attempting to create and dismiss persistent
# notifications. These calls would fail without this fixture since the persistent_notification
# integration is never loaded during a test.
@pytest.fixture(name="skip_notifications", autouse=True)
def skip_notifications_fixture():
    """Skip notification calls."""
    with patch("homeassistant.components.persistent_notification.async_create"), patch(
        "homeassistant.components.persistent_notification.async_dismiss"
    ):
        yield


@pytest.fixture(name="auto_enable_custom_integrations", autouse=True)
def auto_enable_custom_integrations(
    hass: Any, enable_custom_integrations: Any  # noqa: F811
) -> None:
    """Enable custom integrations defined in the test dir."""


# This fixture, when used, will result in calls to async_get_data to return None. To have the call
# return a value, we would add the `return_value=<VALUE_TO_RETURN>` parameter to the patch call.
@pytest.fixture(name="bypass_get_device_info")
def bypass_get_device_info_fixture():
    """Skip calls to get data from API."""
    with patch("custom_components.sunspec.SunSpecApiClient.async_get_device_info"):
        yield


# This fixture, when used, will result in calls to async_get_data to return None. To have the call
# return a value, we would add the `return_value=<VALUE_TO_RETURN>` parameter to the patch call.
@pytest.fixture(name="bypass_get_data")
def bypass_get_data_fixture():
    """Skip calls to get data from API."""
    with patch("custom_components.sunspec.SunSpecApiClient.async_get_data"):
        yield


@pytest.fixture(name="sunspec_client_mock")
def sunspec_client_mock():
    """Skip calls to get data from API."""
    client = modbus_client.FileClientDevice("./tests/test_data/inverter.json")
    client.scan()
    with patch(
        "custom_components.sunspec.SunSpecApiClient.modbus_connect", return_value=client
    ):
        yield


@pytest.fixture(name="sunspec_modbus_client_mock")
def sunspec_modbus_client_mock():
    """Skip calls to get data from API."""
    mock = Mock()
    with patch(
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP", return_value=mock
    ):
        yield


# In this fixture, we are forcing calls to async_get_data to raise an Exception. This is useful
# for exception handling.
@pytest.fixture(name="error_on_get_device_info")
def error_get_device_info_fixture():
    """Simulate error when retrieving data from API."""
    with patch(
        "custom_components.sunspec.SunSpecApiClient.async_get_device_info",
        side_effect=Exception,
    ):
        yield


# In this fixture, we are forcing calls to async_get_data to raise an Exception. This is useful
# for exception handling.
@pytest.fixture(name="error_on_get_data")
def error_get_data_fixture():
    """Simulate error when retrieving data from API."""
    with patch(
        "custom_components.sunspec.SunSpecApiClient.async_get_data",
        side_effect=Exception,
    ):
        yield
