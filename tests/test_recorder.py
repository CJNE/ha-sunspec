"""Test SunSpec recorder platform."""

from homeassistant.core import HomeAssistant

from custom_components.sunspec.recorder import async_custom_equivalent_units

from . import TEST_INVERTER_SENSOR_PF_ID
from . import setup_mock_sunspec_config_entry


async def test_statistics_keep_sunspec_units(
    hass: HomeAssistant, sunspec_client_mock
) -> None:
    """Verify statistics recorded in a SunSpec unit continue in its new unit."""

    await setup_mock_sunspec_config_entry(hass)

    units = async_custom_equivalent_units(hass)[TEST_INVERTER_SENSOR_PF_ID]
    assert units["Pct"] == "%"
