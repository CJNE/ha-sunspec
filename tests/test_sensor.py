"""Test SunSpec sensor."""
from custom_components.sunspec.sensor import ICON_DC_AMPS
from homeassistant.core import HomeAssistant

from . import setup_mock_sunspec_config_entry
from . import TEST_INVERTER_MM_SENSOR_POWER_ENTITY_ID
from . import TEST_INVERTER_MM_SENSOR_STATE_ENTITY_ID
from . import TEST_INVERTER_PREFIX_SENSOR_DC_ENTITY_ID
from . import TEST_INVERTER_SENSOR_DC_ENTITY_ID
from . import TEST_INVERTER_SENSOR_ENERGY_ENTITY_ID
from . import TEST_INVERTER_SENSOR_POWER_ENTITY_ID
from . import TEST_INVERTER_SENSOR_STATE_ENTITY_ID
from . import TEST_INVERTER_SENSOR_VAR_ID
from .const import MOCK_CONFIG_MM
from .const import MOCK_CONFIG_PREFIX


async def test_sensor_overflow_error(
    hass: HomeAssistant, sunspec_client_mock, overflow_error_dca
) -> None:
    """Verify device information includes expected details."""

    await setup_mock_sunspec_config_entry(hass)

    entity_state = hass.states.get(TEST_INVERTER_SENSOR_DC_ENTITY_ID)
    assert entity_state


async def test_sensor_dc(hass: HomeAssistant, sunspec_client_mock) -> None:
    """Verify device information includes expected details."""

    await setup_mock_sunspec_config_entry(hass)

    entity_state = hass.states.get(TEST_INVERTER_SENSOR_DC_ENTITY_ID)
    assert entity_state
    assert entity_state.attributes["icon"] == ICON_DC_AMPS


async def test_sensor_var(hass: HomeAssistant, sunspec_client_mock) -> None:
    """Verify device information includes expected details."""

    await setup_mock_sunspec_config_entry(hass)

    entity_state = hass.states.get(TEST_INVERTER_SENSOR_VAR_ID)
    assert entity_state


async def test_sensor_with_prefix(hass: HomeAssistant, sunspec_client_mock) -> None:
    """Verify device information includes expected details."""

    await setup_mock_sunspec_config_entry(hass, MOCK_CONFIG_PREFIX)

    entity_state = hass.states.get(TEST_INVERTER_PREFIX_SENSOR_DC_ENTITY_ID)
    assert entity_state


async def test_sensor_state(hass: HomeAssistant, sunspec_client_mock) -> None:
    """Verify device information includes expected details."""

    await setup_mock_sunspec_config_entry(hass)

    entity_state = hass.states.get(TEST_INVERTER_SENSOR_STATE_ENTITY_ID)
    assert entity_state
    assert entity_state.state == "MPPT"


async def test_sensor_power(hass: HomeAssistant, sunspec_client_mock) -> None:
    """Verify device information includes expected details."""

    await setup_mock_sunspec_config_entry(hass)

    entity_state = hass.states.get(TEST_INVERTER_SENSOR_POWER_ENTITY_ID)
    assert entity_state
    assert entity_state.state == "800"


async def test_sensor_energy(hass: HomeAssistant, sunspec_client_mock) -> None:
    """Verify device information includes expected details."""

    await setup_mock_sunspec_config_entry(hass)

    entity_state = hass.states.get(TEST_INVERTER_SENSOR_ENERGY_ENTITY_ID)
    assert entity_state
    assert entity_state.state == "100000"


async def test_sensor_state_mm(hass: HomeAssistant, sunspec_client_mock) -> None:
    """Verify device information includes expected details."""

    await setup_mock_sunspec_config_entry(hass, MOCK_CONFIG_MM)

    entity_state = hass.states.get(TEST_INVERTER_MM_SENSOR_STATE_ENTITY_ID)
    assert entity_state
    assert entity_state.state == "OFF"


async def test_sensor_power_mm(hass: HomeAssistant, sunspec_client_mock) -> None:
    """Verify device information includes expected details."""

    await setup_mock_sunspec_config_entry(hass, MOCK_CONFIG_MM)

    entity_state = hass.states.get(TEST_INVERTER_MM_SENSOR_POWER_ENTITY_ID)
    assert entity_state
    assert entity_state.state == "9700"
