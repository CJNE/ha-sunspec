"""Tests for SunSpec integration."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pytest_homeassistant.common import MockConfigEntry

from custom_components.sunspec import DOMAIN
from custom_components.sunspec.api import SunSpecApiClient

from .const import MOCK_CONFIG

TEST_CONFIG_ENTRY_ID = "77889900aa"
TEST_INVERTER_SENSOR_STATE_ENTITY_ID = "sensor.inverter_three_phase_operating_state"
TEST_INVERTER_SENSOR_POWER_ENTITY_ID = "sensor.inverter_three_phase_watts"
TEST_INVERTER_SENSOR_VAR_ID = "sensor.inverter_three_phase_var"
TEST_INVERTER_SENSOR_PF_ID = "sensor.inverter_three_phase_pf"
TEST_INVERTER_SENSOR_ENERGY_ENTITY_ID = "sensor.inverter_three_phase_watthours"
TEST_INVERTER_SENSOR_EVENT_ENTITY_ID = "sensor.inverter_three_phase_event1"
TEST_INVERTER_SENSOR_TMPSNK_ENTITY_ID = (
    "sensor.inverter_three_phase_heat_sink_temperature"
)
TEST_INVERTER_MM_SENSOR_STATE_ENTITY_ID = "sensor.der_ac_measurement_1_operating_state"
TEST_INVERTER_MM_SENSOR_VAR_ID = "sensor.der_ac_measurement_reactive_power"
TEST_INVERTER_MM_SENSOR_VARH_ID = "sensor.der_ac_measurement_total_reactive_energy_inj"
TEST_INVERTER_MM_SENSOR_POWER_ENTITY_ID = "sensor.der_ac_measurement_1_active_power"
TEST_INVERTER_MM_SENSOR_ENERGY_ENTITY_ID = (
    "sensor.der_ac_measurement_total_energy_absorbed"
)
TEST_METER_FLOAT_HZ_ENTITY_ID = "sensor.wye_connect_three_phase_abcn_meter_hz"
TEST_METER_FLOAT_VOLTAGE_ENTITY_ID = (
    "sensor.wye_connect_three_phase_abcn_meter_phase_voltage_an"
)
TEST_METER_FLOAT_ENERGY_ENTITY_ID = (
    "sensor.wye_connect_three_phase_abcn_meter_total_watt_hours_imported"
)
TEST_STATUS_VARH_ENTITY_ID = "sensor.measurements_status_actvarhq1"
TEST_STATUS_VAH_ENTITY_ID = "sensor.measurements_status_actvah"
TEST_INVERTER_SENSOR_DC_ENTITY_ID = (
    "sensor.multiple_mppt_inverter_extension_model_module_0_dc_current"
)
TEST_INVERTER_PREFIX_SENSOR_DC_ENTITY_ID = (
    "sensor.multiple_mppt_inverter_extension_model_test_module_0_dc_current"
)


def create_mock_sunspec_client(hass: HomeAssistant):
    """Create a mock modubs client"""
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)
    return api


def create_mock_sunspec_config_entry(
    hass: HomeAssistant,
    data: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> ConfigEntry:
    """Add a test config entry."""
    config_entry: MockConfigEntry = MockConfigEntry(
        entry_id=TEST_CONFIG_ENTRY_ID,
        domain=DOMAIN,
        data=data or MOCK_CONFIG,
        title="",
        options=options or {},
    )
    config_entry.add_to_hass(hass)
    return config_entry


async def setup_mock_sunspec_config_entry(
    hass: HomeAssistant,
    data: dict[str, Any] | None = None,
    config_entry: ConfigEntry | None = None,
    client: Mock | None = None,
) -> ConfigEntry:
    """Add a mock sunspec config entry to hass."""
    config_entry = config_entry or create_mock_sunspec_config_entry(hass, data)
    client = client or create_mock_sunspec_client(hass)

    with patch(
        "custom_components.sunspec.SunSpecApiClient",
        return_value=client,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    return config_entry


class MockSunSpecDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(self, hass, models) -> None:
        """Initialize."""
        self.api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)
        self.option_model_filter = set(map(lambda m: int(m), models))

    async def _async_update_data(self):
        """Update data via library."""
