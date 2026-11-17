"""Test writing to SunSpec devices."""

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
import pytest
from sunspec2.modbus.client import SunSpecModbusValueError
from sunspec2.modbus.modbus import ModbusClientError
from sunspec2.modbus.modbus import ModbusClientException
from sunspec2.modbus.modbus import ModbusClientTimeout

from custom_components.sunspec import get_sunspec_unique_id
from custom_components.sunspec.api import SunSpecApiClient
from custom_components.sunspec.api import SunSpecModelWrapper
from custom_components.sunspec.const import CONF_ALLOW_WRITING
from custom_components.sunspec.const import CONF_ENABLED_MODELS
from custom_components.sunspec.const import CONF_MODEL_INTERVALS
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


def device_model(mocker, model_id, device):
    """Return the model, which now reads the device's values and writes them."""
    model = SunSpecApiClient.CLIENT_CACHE["test:123:1"].models[model_id][0]
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
    model = device_model(mocker, model_id, device)
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
    device_model(mocker, 123, {"WMaxLimPct": 10000}).write.side_effect = None
    entity = entity_id(hass, "number", 123, "WMaxLimPct")

    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity, "value": 50}, blocking=True
    )

    assert hass.states.get(entity).state == "100.0"


REFUSED = ModbusClientException("Modbus exception: 3")
NO_ANSWER = ModbusClientTimeout("Response timeout")


@pytest.mark.parametrize(
    ("errors", "key", "reconnects", "state"),
    [
        # The device took the value before it refused, and answers the read.
        ({"write": REFUSED}, "write_refused", False, "50.0"),
        # Nothing was sent.
        ({"read": NO_ANSWER}, "write_failed", True, "100.0"),
        # The write was sent, and the device was not read after it.
        ({"write": NO_ANSWER}, "write_unconfirmed", True, STATE_UNAVAILABLE),
        (
            {"write": TimeoutError("timed out")},
            "write_unconfirmed",
            True,
            STATE_UNAVAILABLE,
        ),
        (
            {"write": ModbusClientError("Socket write error")},
            "write_unconfirmed",
            True,
            STATE_UNAVAILABLE,
        ),
        # The device reset the connection instead of answering the write.
        (
            {"write": ConnectionResetError(104, "Connection reset by peer")},
            "write_unconfirmed",
            True,
            STATE_UNAVAILABLE,
        ),
        # The value does not fit the point at the scale factor read before it.
        (
            {"write": SunSpecModbusValueError("Point value error")},
            "write_unconfirmed",
            False,
            STATE_UNAVAILABLE,
        ),
        ({"read back": NO_ANSWER}, "write_unconfirmed", True, STATE_UNAVAILABLE),
        ({"read back": REFUSED}, "write_unconfirmed", False, STATE_UNAVAILABLE),
        (
            {"write": REFUSED, "read back": NO_ANSWER},
            "write_unconfirmed",
            True,
            STATE_UNAVAILABLE,
        ),
    ],
)
async def test_write_error(
    hass, sunspec_client_mock, mocker, errors, key, reconnects, state
):
    """Test that a failed write says why, and shows the value only if the device was read after it."""
    await setup_controls(hass)
    model = device_model(mocker, 123, {"WMaxLimPct": 10000})
    read, take = model.read.side_effect, model.write.side_effect
    reads = iter(("read", "read back"))

    def read_or_fail():
        if error := errors.get(next(reads)):
            raise error
        read()

    def take_and_fail():
        take()
        if "write" in errors:
            raise errors["write"]

    model.read.side_effect = read_or_fail
    model.write.side_effect = take_and_fail
    reconnect = mocker.spy(SunSpecApiClient, "reconnect_next")
    entity = entity_id(hass, "number", 123, "WMaxLimPct")

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "number", "set_value", {"entity_id": entity, "value": 50}, blocking=True
        )

    assert err.value.translation_key == key
    assert reconnect.called is reconnects
    assert hass.states.get(entity).state == state


async def test_write_to_moved_model(hass, sunspec_client_mock, mocker):
    """Test that nothing is written or shown where the device no longer has the model."""
    await setup_controls(hass)
    # Model 124 now sits where the scan found model 123.
    device = {"ID": 124, "WMaxLimPct": 3000}
    model = device_model(mocker, 123, device)
    entity = entity_id(hass, "number", 123, "WMaxLimPct")

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "number", "set_value", {"entity_id": entity, "value": 50}, blocking=True
        )

    assert err.value.translation_key == "write_failed"
    model.write.assert_not_called()
    assert hass.states.get(entity).state == "100.0"

    # The entry is set up anew, and its new scan finds model 123 where it is now.
    device["ID"] = 123
    await hass.async_block_till_done(wait_background_tasks=True)

    assert SunSpecApiClient.modbus_connect.call_count == 2
    assert hass.states.get(entity).state == "30.0"


async def test_unconfirmed_write(hass, sunspec_client_mock, mocker):
    """Test that only the points of a write not read back are unavailable, until a read."""
    mocker.patch("custom_components.sunspec.monotonic", return_value=0)
    entry = create_mock_sunspec_config_entry(
        hass,
        MOCK_CONFIG_CONTROLS,
        {CONF_ALLOW_WRITING: True, CONF_MODEL_INTERVALS: {"123": 3600}},
    )
    await setup_mock_sunspec_config_entry(hass, config_entry=entry)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    device = {"WMaxLimPct": 10000}
    model = device_model(mocker, 123, device)
    read = model.read.side_effect
    written = [
        entity_id(hass, domain, 123, "WMaxLimPct") for domain in ("number", "sensor")
    ]
    others = [
        entity_id(hass, "switch", 123, "WMaxLim_Ena"),
        entity_id(hass, "number", 704, "WMaxLimPct"),
    ]
    get_data = coordinator.api.async_get_data

    def states(entities):
        return [hass.states.get(entity).state for entity in entities]

    async def write_during_poll(model_id):
        # This poll has passed model 123, which is not due, when the write fails.
        if model_id == 124 and not model.write.called:
            model.read.side_effect = [read(), NO_ANSWER]
            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": written[0], "value": 50},
                    blocking=True,
                )
        return await get_data(model_id)

    mocker.patch.object(
        coordinator.api, "async_get_data", side_effect=write_during_poll
    )
    await coordinator.async_refresh()
    assert states(written) == [STATE_UNAVAILABLE, STATE_UNAVAILABLE]
    assert STATE_UNAVAILABLE not in states(others)

    # A write that is then not even sent is not called unconfirmed.
    model.read.side_effect = NO_ANSWER
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN,
            "write",
            {"device_id": device_id(hass, "controls"), "points": {"WMaxLimPct": 50}},
            blocking=True,
        )
    assert err.value.translation_key == "write_failed"

    # A poll the device refuses the model in leaves both as they are.
    model.read.side_effect = REFUSED
    await coordinator.async_refresh()
    assert states(written) == [STATE_UNAVAILABLE, STATE_UNAVAILABLE]
    assert STATE_UNAVAILABLE not in states(others)

    # The next read shows what the device holds, and nothing is written again.
    device["WMaxLimPct"] = 7500
    model.read.side_effect = read
    await coordinator.async_refresh()
    assert states(written) == ["75.0", "75.0"]
    model.write.assert_called_once()

    # So does the read before a later write, even one refused before it is sent.
    model.read.side_effect = [read(), NO_ANSWER]
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": written[0], "value": 60}, blocking=True
        )
    device["WMaxLim_Ena"] = None
    model.read.side_effect = read
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": others[0]}, blocking=True
        )
    assert err.value.translation_key == "write_refused"
    assert states(written) == ["60.0", "60.0"]


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
    model = device_model(mocker, model_id, device)
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
    model = device_model(mocker, 123, {})

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
    model = device_model(mocker, 123, {})

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "write",
            {"device_id": device_id(hass, device), "points": points},
            blocking=True,
        )

    assert err.value.translation_key == key
    model.write.assert_not_called()
