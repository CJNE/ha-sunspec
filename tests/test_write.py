"""Test writing to SunSpec devices."""

from homeassistant.exceptions import HomeAssistantError
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from modbus_connection import IllegalDataValueError
from modbus_connection import ModbusConnectionError
from modbus_connection import ModbusTimeoutError
import pytest

from custom_components.sunspec import get_sunspec_unique_id
from custom_components.sunspec.api import SunSpecModelWrapper
from custom_components.sunspec.const import CONF_ALLOW_WRITING
from custom_components.sunspec.const import CONF_ENABLED_MODELS
from custom_components.sunspec.const import CONF_SCAN_INTERVAL
from custom_components.sunspec.const import DOMAIN

from . import TEST_CONFIG_ENTRY_ID
from . import create_mock_sunspec_config_entry
from . import setup_mock_sunspec_config_entry
from .const import MOCK_CONFIG_CONTROLS
from .const import MOCK_CONFIG_STEP_1

pytestmark = pytest.mark.parametrize("sunspec_fixture", ["controls.json"])


@pytest.fixture(autouse=True)
def no_read_delay(mocker):
    """Skip the pauses between Modbus requests."""
    mocker.patch("custom_components.sunspec.api.time.sleep")


async def setup_controls(hass, allow_writing=True):
    """Set up an entry for the controls fixture."""
    entry = create_mock_sunspec_config_entry(
        hass, MOCK_CONFIG_CONTROLS, {CONF_ALLOW_WRITING: allow_writing}
    )
    return await setup_mock_sunspec_config_entry(hass, config_entry=entry)


def entity_id(hass, domain, model_id, key):
    """Return the entity ID of the entity for a point."""
    return er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, get_sunspec_unique_id(TEST_CONFIG_ENTRY_ID, key, model_id, 0)
    )


def device_id(hass, name):
    """Return the ID of the entry's device for a model."""
    return next(
        device.id
        for device in dr.async_entries_for_config_entry(
            dr.async_get(hass), TEST_CONFIG_ENTRY_ID
        )
        if (DOMAIN, TEST_CONFIG_ENTRY_ID, name) in device.identifiers
    )


def device_model(hass, mocker, model_id, device):
    """Return the model, which now reads the device's values and writes them."""
    api = hass.data[DOMAIN][TEST_CONFIG_ENTRY_ID].api
    model = api.get_client().models[model_id][0]
    point = SunSpecModelWrapper([model]).getPoint
    mocker.patch.object(
        model,
        "read",
        side_effect=lambda: [
            point(key).set_value(value, dirty=False) for key, value in device.items()
        ],
    )
    mocker.patch.object(
        model,
        "write",
        side_effect=lambda: device.update({key: point(key).value for key in device}),
    )
    return model


@pytest.mark.parametrize(
    ("allow_writing", "entities"),
    [
        (False, {"number": 0, "select": 0, "switch": 0}),
        (True, {"number": 24, "select": 6, "switch": 9}),
    ],
)
async def test_write_entities_follow_allow_writing(
    hass, sunspec_client_mock, allow_writing, entities
):
    """Test that Allow writing gives the implemented writable points of 123, 124 and 704 entities."""
    await setup_controls(hass, allow_writing)

    assert {
        domain: len(hass.states.async_entity_ids(domain)) for domain in entities
    } == entities


async def test_turning_writing_off_removes_write_entities(hass, sunspec_client_mock):
    """Test that turning Allow writing off in Configure removes the write entities."""
    entry = await setup_controls(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG_STEP_1
    )
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_ENABLED_MODELS: MOCK_CONFIG_CONTROLS[CONF_ENABLED_MODELS],
            CONF_SCAN_INTERVAL: 10,
            CONF_ALLOW_WRITING: False,
        },
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    registry = er.async_get(hass)
    assert {
        entity.domain
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
    } == {"sensor"}


@pytest.mark.parametrize(
    ("domain", "service", "data", "model_id", "key", "device", "written", "state"),
    [
        (
            "number",
            "set_value",
            {"value": 50},
            123,
            "WMaxLimPct",
            {"WMaxLimPct_SF": -1},
            {"WMaxLimPct": 500},
            "50.0",
        ),
        (
            "number",
            "set_value",
            {"value": -50},
            124,
            "InWRte",
            {},
            {"InWRte": -5000},
            "-50.0",
        ),
        (
            "number",
            "set_value",
            {"value": 0.95},
            704,
            "PFWInj:0:PF",
            {},
            {"PFWInj:0:PF": 950},
            "0.95",
        ),
        ("switch", "turn_on", {}, 123, "WMaxLim_Ena", {}, {"WMaxLim_Ena": 1}, "on"),
        (
            "switch",
            "turn_off",
            {},
            123,
            "OutPFSet_Ena",
            {"OutPFSet_Ena": 1},
            {"OutPFSet_Ena": 0},
            "off",
        ),
        (
            "select",
            "select_option",
            {"option": "DISCONNECT"},
            123,
            "Conn",
            {},
            {"Conn": 0},
            "DISCONNECT",
        ),
        (
            "switch",
            "turn_on",
            {},
            124,
            "StorCtl_Mod:0",
            {"StorCtl_Mod": 2},
            {"StorCtl_Mod": 3},
            "on",
        ),
        (
            "switch",
            "turn_off",
            {},
            124,
            "StorCtl_Mod:1",
            {"StorCtl_Mod": 3},
            {"StorCtl_Mod": 1},
            "off",
        ),
    ],
)
async def test_write_entity(
    hass,
    sunspec_client_mock,
    mocker,
    domain,
    service,
    data,
    model_id,
    key,
    device,
    written,
    state,
):
    """Test that an entity writes its point onto what the device holds now."""
    await setup_controls(hass)
    model = device_model(hass, mocker, model_id, device)
    entity = entity_id(hass, domain, model_id, key)

    await hass.services.async_call(
        domain, service, {"entity_id": entity, **data}, blocking=True
    )

    point = SunSpecModelWrapper([model]).getPoint
    assert {name: point(name).value for name in written} == written
    assert hass.states.get(entity).state == state


async def test_write_ignored(hass, sunspec_client_mock, mocker):
    """Test that a write the device ignores without an error leaves its value shown."""
    await setup_controls(hass)
    device_model(hass, mocker, 123, {"WMaxLimPct": 10000}).write.side_effect = None
    entity = entity_id(hass, "number", 123, "WMaxLimPct")

    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity, "value": 50}, blocking=True
    )

    assert hass.states.get(entity).state == "100.0"


@pytest.mark.parametrize(
    ("error", "key", "state"),
    [
        # The device took the value before it refused, and answers the read.
        (IllegalDataValueError(), "write_refused", "50.0"),
        (ModbusTimeoutError("Response timeout"), "write_failed", "100.0"),
        (ModbusConnectionError("Socket write error"), "write_failed", "100.0"),
    ],
)
async def test_write_error(hass, sunspec_client_mock, mocker, error, key, state):
    """Test that a failed write says why and shows the device's value, read again if it answered."""
    await setup_controls(hass)
    model = device_model(hass, mocker, 123, {"WMaxLimPct": 10000})
    take = model.write.side_effect

    def take_and_fail():
        take()
        raise error

    model.write.side_effect = take_and_fail
    entity = entity_id(hass, "number", 123, "WMaxLimPct")

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "number", "set_value", {"entity_id": entity, "value": 50}, blocking=True
        )

    assert err.value.translation_key == key
    assert hass.states.get(entity).state == state


@pytest.mark.parametrize(
    ("domain", "service", "data", "model_id", "key", "device"),
    [
        ("switch", "turn_on", {}, 124, "StorCtl_Mod:0", {"StorCtl_Mod": None}),
        (
            "number",
            "set_value",
            {"value": 50},
            123,
            "WMaxLimPct",
            {"WMaxLimPct_SF": None},
        ),
    ],
)
async def test_write_not_implemented(
    hass, sunspec_client_mock, mocker, domain, service, data, model_id, key, device
):
    """Test that a point the device no longer implements, or scales, is not written."""
    await setup_controls(hass)
    model = device_model(hass, mocker, model_id, device)
    entity = entity_id(hass, domain, model_id, key)

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            domain, service, {"entity_id": entity, **data}, blocking=True
        )

    assert err.value.translation_key == "write_refused"
    model.write.assert_not_called()


@pytest.mark.parametrize(
    ("model_id", "key", "lowest", "highest", "step"),
    [
        (123, "WMaxLimPct", 0, 100, 0.01),
        (124, "InWRte", -100, 100, 0.01),
        (123, "OutPFSet", -1, 1, 0.0001),
        (124, "WChaMax", 0, 65534, 1),
        (704, "WMaxLimPctRvrtTms", 0, 4294967294, 1),
    ],
)
async def test_number_range(
    hass, sunspec_client_mock, model_id, key, lowest, highest, step
):
    """Test that a number takes what its point holds, percent and power factor in their range."""
    await setup_controls(hass)

    attributes = hass.states.get(entity_id(hass, "number", model_id, key)).attributes
    assert (attributes["min"], attributes["max"], attributes["step"]) == pytest.approx(
        (lowest, highest, step)
    )


async def test_write_action(hass, sunspec_client_mock, mocker):
    """Test that the action writes points of a model in one write."""
    await setup_controls(hass)
    model = device_model(hass, mocker, 123, {})

    await hass.services.async_call(
        DOMAIN,
        "write",
        {
            "device_id": device_id(hass, "controls"),
            "points": {"WMaxLimPct": 50, "WMaxLim_Ena": "ENABLED"},
        },
        blocking=True,
    )

    assert (model.points["WMaxLimPct"].value, model.points["WMaxLim_Ena"].value) == (
        5000,
        1,
    )
    model.write.assert_called_once()
    assert hass.states.get(entity_id(hass, "number", 123, "WMaxLimPct")).state == (
        "50.0"
    )


@pytest.mark.parametrize(
    ("allow_writing", "device", "points", "key"),
    [
        (False, "controls", {"WMaxLimPct": 50}, "not_writable_device"),
        (True, "settings", {"WMax": 3000}, "not_writable_device"),
        (True, "controls", {"Unknown": 1}, "not_writable_point"),
        (True, "controls", {"WMaxLimPct_SF": 0}, "not_writable_point"),
        (True, "controls", {"WMaxLimPct_RmpTms": 5}, "not_writable_point"),
        (True, "controls", {"WMaxLimPct": 150}, "invalid_value"),
        (True, "controls", {"WMaxLim_Ena": "ON"}, "invalid_value"),
        (True, "controls", {"Conn": 1}, "invalid_value"),
    ],
)
async def test_write_action_refused(
    hass, sunspec_client_mock, mocker, allow_writing, device, points, key
):
    """Test that the action writes nothing to a device or point it may not write."""
    await setup_controls(hass, allow_writing)
    model = device_model(hass, mocker, 123, {})

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "write",
            {"device_id": device_id(hass, device), "points": points},
            blocking=True,
        )

    assert err.value.translation_key == key
    model.write.assert_not_called()
