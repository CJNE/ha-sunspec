"""Test SunSpec sensor."""

from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.core import State
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant.common import mock_restore_cache_with_extra_data

from custom_components.sunspec import get_sunspec_unique_id
from custom_components.sunspec.api import SunSpecApiClient
from custom_components.sunspec.const import CONF_ENABLED_MODELS
from custom_components.sunspec.const import DOMAIN
from custom_components.sunspec.sensor import ICON_DC_AMPS

from . import TEST_CONFIG_ENTRY_ID
from . import TEST_INVERTER_MM_SENSOR_ENERGY_ENTITY_ID
from . import TEST_INVERTER_MM_SENSOR_POWER_ENTITY_ID
from . import TEST_INVERTER_MM_SENSOR_STATE_ENTITY_ID
from . import TEST_INVERTER_MM_SENSOR_VAR_ID
from . import TEST_INVERTER_MM_SENSOR_VARH_ID
from . import TEST_INVERTER_PREFIX_SENSOR_DC_ENTITY_ID
from . import TEST_INVERTER_SENSOR_DC_ENTITY_ID
from . import TEST_INVERTER_SENSOR_ENERGY_ENTITY_ID
from . import TEST_INVERTER_SENSOR_EVENT_ENTITY_ID
from . import TEST_INVERTER_SENSOR_PF_ID
from . import TEST_INVERTER_SENSOR_POWER_ENTITY_ID
from . import TEST_INVERTER_SENSOR_STATE_ENTITY_ID
from . import TEST_INVERTER_SENSOR_TMPSNK_ENTITY_ID
from . import TEST_INVERTER_SENSOR_VAR_ID
from . import TEST_METER_FLOAT_ENERGY_ENTITY_ID
from . import TEST_METER_FLOAT_HZ_ENTITY_ID
from . import TEST_METER_FLOAT_VOLTAGE_ENTITY_ID
from . import TEST_STATUS_VAH_ENTITY_ID
from . import TEST_STATUS_VARH_ENTITY_ID
from . import setup_mock_sunspec_config_entry
from .const import MOCK_CONFIG
from .const import MOCK_CONFIG_METER_FLOAT
from .const import MOCK_CONFIG_MM
from .const import MOCK_CONFIG_PREFIX
from .const import MOCK_CONFIG_STATUS


async def test_sensor_overflow_error(
    hass: HomeAssistant, sunspec_client_mock, overflow_error_dca
) -> None:
    """Verify a value that overflows leaves the sensor in place."""

    await setup_mock_sunspec_config_entry(hass)

    entity_state = hass.states.get(TEST_INVERTER_SENSOR_DC_ENTITY_ID)
    assert entity_state


async def test_sensor_dc(hass: HomeAssistant, sunspec_client_mock) -> None:
    """Verify a DC current sensor gets the DC icon."""

    await setup_mock_sunspec_config_entry(hass)

    entity_state = hass.states.get(TEST_INVERTER_SENSOR_DC_ENTITY_ID)
    assert entity_state
    assert entity_state.attributes["icon"] == ICON_DC_AMPS


@pytest.mark.parametrize(
    ("sunspec_fixture", "config", "entity_id", "unit", "device_class"),
    [
        ("inverter.json", None, TEST_INVERTER_SENSOR_VAR_ID, "var", "reactive_power"),
        ("inverter.json", None, TEST_INVERTER_SENSOR_PF_ID, "%", None),
        (
            "inverter.json",
            MOCK_CONFIG_MM,
            TEST_INVERTER_MM_SENSOR_VAR_ID,
            "var",
            "reactive_power",
        ),
        (
            "inverter.json",
            MOCK_CONFIG_MM,
            TEST_INVERTER_MM_SENSOR_VARH_ID,
            "varh",
            "reactive_energy",
        ),
        (
            "status.json",
            MOCK_CONFIG_STATUS,
            TEST_STATUS_VARH_ENTITY_ID,
            "varh",
            "reactive_energy",
        ),
        # Home Assistant has no device class for apparent energy.
        ("status.json", MOCK_CONFIG_STATUS, TEST_STATUS_VAH_ENTITY_ID, "VAh", None),
        # An angle, not a temperature.
        (
            "inverter.json",
            {**MOCK_CONFIG_MM, "models_enabled": [304]},
            "sensor.inclinometer_model_incl_0_x",
            "°",
            None,
        ),
    ],
)
async def test_sensor_unit(
    hass: HomeAssistant, sunspec_client_mock, config, entity_id, unit, device_class
) -> None:
    """Verify SunSpec units show as Home Assistant units and device classes."""

    await setup_mock_sunspec_config_entry(hass, config)

    entity_state = hass.states.get(entity_id)
    assert entity_state.attributes["unit_of_measurement"] == unit
    assert entity_state.attributes.get("device_class") == device_class


@pytest.mark.parametrize(
    ("config", "device_name", "entity_id", "name"),
    [
        (
            None,
            None,
            TEST_INVERTER_SENSOR_DC_ENTITY_ID,
            "Multiple MPPT Inverter Extension Model Module 0 DC Current",
        ),
        (
            MOCK_CONFIG_PREFIX,
            None,
            TEST_INVERTER_PREFIX_SENSOR_DC_ENTITY_ID,
            "Multiple MPPT Inverter Extension Model Test module 0 DC Current",
        ),
        # The prefix keeps the letters it was entered with.
        (
            {**MOCK_CONFIG_PREFIX, "prefix": "SE7600"},
            None,
            "sensor.multiple_mppt_inverter_extension_model_se7600_module_0_dc_current",
            "Multiple MPPT Inverter Extension Model SE7600 module 0 DC Current",
        ),
        # A device the user renamed keeps the prefix in its entities' names.
        (
            MOCK_CONFIG_PREFIX,
            "Roof",
            TEST_INVERTER_PREFIX_SENSOR_DC_ENTITY_ID,
            "Roof Test module 0 DC Current",
        ),
        # The second instance of a model.
        (
            MOCK_CONFIG_MM,
            None,
            TEST_INVERTER_MM_SENSOR_POWER_ENTITY_ID,
            "DER AC Measurement 1 Active Power",
        ),
    ],
)
async def test_sensor_name(
    hass: HomeAssistant, sunspec_client_mock, config, device_name, entity_id, name
) -> None:
    """Verify a name gives the device, the prefix and the point, the model once."""

    await setup_mock_sunspec_config_entry(hass, config)
    if device_name:
        device_id = er.async_get(hass).async_get(entity_id).device_id
        dr.async_get(hass).async_update_device(device_id, name_by_user=device_name)
        await hass.async_block_till_done()

    assert hass.states.get(entity_id).attributes["friendly_name"] == name


async def test_sensor_state(hass: HomeAssistant, sunspec_client_mock) -> None:
    """Verify the operating state shows its symbol."""

    await setup_mock_sunspec_config_entry(hass)

    entity_state = hass.states.get(TEST_INVERTER_SENSOR_STATE_ENTITY_ID)
    assert entity_state
    assert entity_state.state == "MPPT"


async def test_sensor_power(hass: HomeAssistant, sunspec_client_mock) -> None:
    """Verify the power sensor shows the device's value."""

    await setup_mock_sunspec_config_entry(hass)

    entity_state = hass.states.get(TEST_INVERTER_SENSOR_POWER_ENTITY_ID)
    assert entity_state
    assert entity_state.state == "800"


async def test_sensor_energy(hass: HomeAssistant, sunspec_client_mock) -> None:
    """Verify the energy sensor shows the device's value."""

    await setup_mock_sunspec_config_entry(hass)

    entity_state = hass.states.get(TEST_INVERTER_SENSOR_ENERGY_ENTITY_ID)
    assert entity_state
    assert entity_state.state == "100000"


@pytest.mark.parametrize(
    ("sunspec_fixture", "config", "entity_id", "unit"),
    [
        (
            "inverter.json",
            MOCK_CONFIG_MM,
            TEST_INVERTER_MM_SENSOR_ENERGY_ENTITY_ID,
            "Wh",
        ),
        (
            "inverter.json",
            MOCK_CONFIG_MM,
            "sensor.der_ac_measurement_total_reactive_energy_abs",
            "varh",
        ),
        ("status.json", MOCK_CONFIG_STATUS, TEST_STATUS_VARH_ENTITY_ID, "varh"),
        ("status.json", MOCK_CONFIG_STATUS, TEST_STATUS_VAH_ENTITY_ID, "VAh"),
    ],
)
async def test_sensor_energy_restored(
    hass: HomeAssistant, sunspec_client_mock, config, entity_id, unit
) -> None:
    """Verify an energy counter reading 0 keeps its value from before a restart, as a running total."""
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(entity_id, "1234"),
                {"native_value": 1234, "native_unit_of_measurement": unit},
            )
        ],
    )

    await setup_mock_sunspec_config_entry(hass, config)

    entity_state = hass.states.get(entity_id)
    assert entity_state.state == "1234"
    assert entity_state.attributes["state_class"] == "total_increasing"


async def test_sensor_added_with_first_value(
    hass: HomeAssistant, sunspec_client_mock
) -> None:
    """Verify a point without a value at setup gets its sensor with its first value."""

    config_entry = await setup_mock_sunspec_config_entry(hass)
    assert hass.states.get(TEST_INVERTER_SENSOR_TMPSNK_ENTITY_ID) is None

    client = SunSpecApiClient.CLIENT_CACHE["test:123:1"]
    client.models[103][0].points["TmpSnk"].value = 45
    await hass.data[DOMAIN][config_entry.entry_id].async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get(TEST_INVERTER_SENSOR_TMPSNK_ENTITY_ID).state == "45"


@pytest.mark.parametrize("sunspec_fixture", ["two_instances.json"])
@pytest.mark.parametrize(
    ("key", "model_id", "model_index", "state"),
    [
        ("TotWhExp", 203, 0, "1000"),
        # Only the second meter implements it.
        ("TotWhImp", 203, 1, "7000"),
        # Only the first meter implements it.
        ("AphA", 203, 1, None),
        # The second instance of 160 has one module, the first two.
        ("module:1:DCA", 160, 0, "92"),
        ("module:1:DCA", 160, 1, None),
    ],
)
async def test_sensor_instances(
    hass: HomeAssistant, sunspec_client_mock, key, model_id, model_index, state
) -> None:
    """Verify each instance of a model gets the sensors of the points it has."""

    config = {**MOCK_CONFIG, CONF_ENABLED_MODELS: [160, 203]}
    await setup_mock_sunspec_config_entry(hass, config)

    unique_id = get_sunspec_unique_id(TEST_CONFIG_ENTRY_ID, key, model_id, model_index)
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, unique_id)
    assert (entity_id and hass.states.get(entity_id).state) == state


@pytest.mark.parametrize("sunspec_fixture", ["gps.json"])
@pytest.mark.parametrize(
    ("key", "state"),
    [
        # Text, with a format as its unit: YYYYMMDD, hhmmss.sssZ, text.
        ("Date", None),
        ("Tm", None),
        ("Loc", None),
        ("Alt", "12"),
    ],
)
async def test_sensor_text(
    hass: HomeAssistant, sunspec_client_mock, key, state
) -> None:
    """Verify text points get no sensor, whatever their definition gives as unit."""

    await setup_mock_sunspec_config_entry(
        hass, {**MOCK_CONFIG, CONF_ENABLED_MODELS: [305]}
    )

    unique_id = get_sunspec_unique_id(TEST_CONFIG_ENTRY_ID, key, 305, 0)
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, unique_id)
    assert (entity_id and hass.states.get(entity_id).state) == state


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


@pytest.mark.parametrize(
    ("value", "state"), [(3, "GROUND_FAULT,DC_OVER_VOLT"), (None, STATE_UNKNOWN)]
)
async def test_sensor_bitfield(
    hass: HomeAssistant, sunspec_client_mock, value, state
) -> None:
    """Verify a bitfield reports every flag set, and unknown once it reads "not implemented"."""

    config_entry = await setup_mock_sunspec_config_entry(hass)
    client = SunSpecApiClient.CLIENT_CACHE["test:123:1"]
    client.models[103][0].points["Evt1"].value = value
    await hass.data[DOMAIN][config_entry.entry_id].async_refresh()

    assert hass.states.get(TEST_INVERTER_SENSOR_EVENT_ENTITY_ID).state == state


async def test_sensor_state_mm(hass: HomeAssistant, sunspec_client_mock) -> None:
    """Verify the operating state of model 701 shows its symbol."""

    await setup_mock_sunspec_config_entry(hass, MOCK_CONFIG_MM)

    entity_state = hass.states.get(TEST_INVERTER_MM_SENSOR_STATE_ENTITY_ID)
    assert entity_state
    assert entity_state.state == "OFF"


async def test_sensor_power_mm(hass: HomeAssistant, sunspec_client_mock) -> None:
    """Verify the power sensor of model 701 shows the device's value."""

    await setup_mock_sunspec_config_entry(hass, MOCK_CONFIG_MM)

    entity_state = hass.states.get(TEST_INVERTER_MM_SENSOR_POWER_ENTITY_ID)
    assert entity_state
    assert entity_state.state == "9700"


@pytest.mark.parametrize("sunspec_fixture", ["status.json"])
@pytest.mark.parametrize(
    ("entity_id", "state"),
    [
        # A 16-bit bitfield.
        ("sensor.measurements_status_pvconn", "CONNECTED,AVAILABLE,OPERATING"),
        # A 32-bit enum, without symbols in its definition.
        ("sensor.basic_aggregator_vendor_control", "5"),
    ],
)
async def test_sensor_flags_and_enums(
    hass: HomeAssistant, sunspec_client_mock, entity_id, state
) -> None:
    """Verify bitfields and enums of each size get their sensors."""

    config = {**MOCK_CONFIG_MM, "models_enabled": [2, 122]}
    await setup_mock_sunspec_config_entry(hass, config)

    assert hass.states.get(entity_id).state == state
