"""Tests for SunSpec integration."""
import sunspec2.file.client as modbus_client
from custom_components.sunspec.api import (
    SunSpecApiClient,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator


def create_mock_client():
    """Create a mock modubs client"""
    client = modbus_client.FileClientDevice("./tests/test_data/inverter.json")
    client.scan()
    return client


class MockSunSpecDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(self, hass, models) -> None:
        """Initialize."""
        self.api = SunSpecApiClient(host="test", port=123, slave_id=1, hass=hass)
        self.option_model_filter = set(map(lambda m: int(m), models))

    async def _async_update_data(self):
        """Update data via library."""
