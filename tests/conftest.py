"""Global fixtures for SunSpec integration."""

import logging
from typing import Any
from unittest.mock import Mock
from unittest.mock import patch

import pytest
import sunspec2.file.client as modbus_client

from custom_components.sunspec.api import ConnectionError
from custom_components.sunspec.api import ConnectionTimeoutError

pytest_plugins = "pytest_homeassistant_custom_component"
_LOGGER: logging.Logger = logging.getLogger(__package__)


class MockFileClientDeviceNotConnected(modbus_client.FileClientDevice):
    def is_connected(self):
        return False

    def connect(self):
        return True


class MockFileClientDevice(modbus_client.FileClientDevice):
    def is_connected(self):
        return True

    def scan(self, progress=None):
        print(progress)
        if progress is not None:
            if not progress("Mock scan"):
                return
        return super().scan()

    def connect(self):
        return True


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


@pytest.fixture
def sunspec_client_mock():
    """Skip calls to get data from API."""
    client = MockFileClientDevice("./tests/test_data/inverter.json")
    client.scan()
    with patch(
        "custom_components.sunspec.SunSpecApiClient.modbus_connect", return_value=client
    ), patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
    ):
        yield


# In this fixture, we are forcing calls to async_get_data to raise an Exception. This is useful
# for exception handling.
@pytest.fixture
def sunspec_client_mock_connect_error():
    """Simulate connection error when retrieving data from API."""
    client = MockFileClientDevice("./tests/test_data/inverter.json")
    with patch(
        "custom_components.sunspec.SunSpecApiClient.modbus_connect", return_value=client
    ), patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
    ), patch(
        "custom_components.sunspec.SunSpecApiClient.async_get_models",
        side_effect=ConnectionError,
    ):
        yield


@pytest.fixture
def sunspec_client_mock_not_connected():
    """Skip calls to get data from API."""
    client = MockFileClientDeviceNotConnected("./tests/test_data/inverter.json")
    client.scan()
    with patch(
        "custom_components.sunspec.SunSpecApiClient.modbus_connect", return_value=client
    ), patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
    ):
        yield


@pytest.fixture(name="sunspec_modbus_client_mock")
def sunspec_modbus_client_mock():
    """Skip calls to get data from API."""
    mock = Mock()
    with patch(
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP", return_value=mock
    ), patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
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
    ), patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
    ):
        yield


# In this fixture, we are forcing calls to async_get_data to raise an Exception. This is useful
# for exception handling.
@pytest.fixture
def error_on_get_data():
    """Simulate error when retrieving data from API."""
    client = MockFileClientDevice("./tests/test_data/inverter.json")
    client.scan()
    with patch(
        "custom_components.sunspec.SunSpecApiClient.modbus_connect", return_value=client
    ), patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
    ), patch(
        "custom_components.sunspec.SunSpecApiClient.async_get_data",
        side_effect=ConnectionError,
    ):
        yield


# In this fixture, we are forcing calls to async_get_data to raise an Exception. This is useful
# for exception handling.
@pytest.fixture
def timeout_error_on_get_data():
    """Simulate timeout error when retrieving data from API."""
    client = MockFileClientDevice("./tests/test_data/inverter.json")
    client.scan()
    with patch(
        "custom_components.sunspec.SunSpecApiClient.get_client", return_value=client
    ), patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
    ), patch(
        "custom_components.sunspec.SunSpecApiClient.async_get_data",
        side_effect=ConnectionTimeoutError,
    ):
        yield


# In this fixture, we are forcing calls to async_get_data to raise an Exception. This is useful
# for exception handling.
@pytest.fixture
def connect_error_on_get_data():
    """Simulate connection error when retrieving data from API."""
    client = MockFileClientDevice("./tests/test_data/inverter.json")
    with patch(
        "custom_components.sunspec.SunSpecApiClient.modbus_connect", return_value=client
    ), patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
    ), patch(
        "custom_components.sunspec.SunSpecApiClient.async_get_data",
        side_effect=ConnectionError,
    ):
        yield


@pytest.fixture
def overflow_error_dca():
    """Simulate overflow error for getValue from API."""

    def my_side_effect(*args, **kwargs):
        if args[0] == "DCA":
            raise OverflowError()
        return 1

    with patch(
        "custom_components.sunspec.api.SunSpecModelWrapper.getValue",
        side_effect=my_side_effect,
    ):
        yield
