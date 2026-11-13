"""Test SunSpec sensor."""

from homeassistant.core import HomeAssistant
from homeassistant.core import State
import pytest
from pytest_homeassistant.common import mock_restore_cache_with_extra_data

from custom_components.sunspec.api import SunSpecApiClient
from custom_components.sunspec.const import DOMAIN
from custom_components.sunspec.sensor import ICON_DC_AMPS

from . import TEST_INVERTER_MM_SENSOR_ENERGY_ENTITY_ID
from . import TEST_INVERTER_MM_SENSOR_POWER_ENTITY_ID
from . import TEST_INVERTER_MM_SENSOR_STATE_ENTITY_ID
from . import TEST_INVERTER_PREFIX_SENSOR_DC_ENTITY_ID
from . import TEST_INVERTER_SENSOR_DC_ENTITY_ID
from . import TEST_INVERTER_SENSOR_ENERGY_ENTITY_ID
from . import TEST_INVERTER_SENSOR_EVENT_ENTITY_ID
from . import TEST_INVERTER_SENSOR_POWER_ENTITY_ID
from . import TEST_INVERTER_SENSOR_STATE_ENTITY_ID
from . import TEST_INVERTER_SENSOR_TMPSNK_ENTITY_ID
from . import TEST_INVERTER_SENSOR_VAR_ID
from . import TEST_METER_FLOAT_ENERGY_ENTITY_ID
from . import TEST_METER_FLOAT_HZ_ENTITY_ID
from . import TEST_METER_FLOAT_VOLTAGE_ENTITY_ID
from . import setup_mock_sunspec_config_entry
from .const import MOCK_CONFIG_METER_FLOAT
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


async def test_sensor_energy_restored(hass: HomeAssistant, sunspec_client_mock) -> None:
    """Verify an energy sensor reading 0 keeps its value from before a restart."""
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(TEST_INVERTER_MM_SENSOR_ENERGY_ENTITY_ID, "1234"),
                {"native_value": 1234, "native_unit_of_measurement": "Wh"},
            )
        ],
    )

    await setup_mock_sunspec_config_entry(hass, MOCK_CONFIG_MM)

    entity_state = hass.states.get(TEST_INVERTER_MM_SENSOR_ENERGY_ENTITY_ID)
    assert entity_state.state == "1234"


async def test_sensor_added_with_first_value(
    hass: HomeAssistant, sunspec_client_mock
) -> None:
    """Verify a point without a value at setup gets its sensor with its first value."""

    config_entry = await setup_mock_sunspec_config_entry(hass)
    assert hass.states.get(TEST_INVERTER_SENSOR_TMPSNK_ENTITY_ID) is None

    client = SunSpecApiClient.CLIENT_CACHE["test:123:1"]
    client.models[103][0].points["TmpSnk"].value = 45
    await hass.data[DOMAIN][config_entry.entry_id].async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(TEST_INVERTER_SENSOR_TMPSNK_ENTITY_ID).state == "45"


@pytest.mark.parametrize("sunspec_fixture", ["meter_float.json"])
@pytest.mark.parametrize(
    ("entity_id", "state"),
    [
        (TEST_METER_FLOAT_HZ_ENTITY_ID, "49.97"),
        (TEST_METER_FLOAT_VOLTAGE_ENTITY_ID, "230.1"),
        (TEST_METER_FLOAT_ENERGY_ENTITY_ID, "25000002.0"),
    ],
)
async def test_sensor_float32(
    hass: HomeAssistant, sunspec_client_mock, entity_id, state
) -> None:
    """Verify a float32 point reports the decimal the device sent."""

    await setup_mock_sunspec_config_entry(hass, MOCK_CONFIG_METER_FLOAT)

    assert hass.states.get(entity_id).state == state


async def test_sensor_bitfield(hass: HomeAssistant, sunspec_client_mock) -> None:
    """Verify a bitfield with several flags set reports all of them."""

    await setup_mock_sunspec_config_entry(hass)

    entity_state = hass.states.get(TEST_INVERTER_SENSOR_EVENT_ENTITY_ID)
    assert entity_state
    assert entity_state.state == "GROUND_FAULT,DC_OVER_VOLT"


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
