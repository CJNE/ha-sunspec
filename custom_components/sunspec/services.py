"""The action that writes points of a SunSpec model."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.core import ServiceCall
from homeassistant.core import callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
import voluptuous as vol

from .const import CONF_ALLOW_WRITING
from .const import DOMAIN
from .const import WRITE_MODELS

ATTR_POINTS = "points"
WRITE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_POINTS): vol.All(
            {cv.string: vol.Any(vol.Coerce(float), cv.string)}, vol.Length(min=1)
        ),
    }
)


def writable_model(hass: HomeAssistant, device_id):
    """Return the coordinator and model ID of a model's device that may write."""
    device = dr.async_get(hass).async_get(device_id)
    for identifier in device.identifiers if device else ():
        entry = hass.config_entries.async_get_entry(identifier[1])
        if (
            entry is None
            or entry.domain != DOMAIN
            or entry.state is not ConfigEntryState.LOADED
            or not entry.options.get(CONF_ALLOW_WRITING)
        ):
            continue
        coordinator = hass.data[DOMAIN][entry.entry_id]
        for model_id, model in (coordinator.data or {}).items():
            if (
                model_id in WRITE_MODELS
                and model.getGroupMeta()["name"] == identifier[2]
            ):
                return coordinator, model_id
    raise ServiceValidationError(
        translation_domain=DOMAIN, translation_key="not_writable_device"
    )


def point_value(model, key, value):
    """Return the value to write to a point: an enum's by its name, else a number."""
    meta = model.getMeta(key)
    if meta["type"].startswith("enum"):
        symbols = {symbol["name"]: symbol["value"] for symbol in meta["symbols"]}
        if value in symbols:
            return symbols[value]
    elif isinstance(value, float):
        lowest, highest, _ = model.getRange(key)
        if lowest <= value <= highest:
            return value
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="invalid_value",
        translation_placeholders={"point": key, "value": str(value)},
    )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the write action."""

    async def write(call: ServiceCall) -> None:
        coordinator, model_id = writable_model(hass, call.data[ATTR_DEVICE_ID])
        model = coordinator.data[model_id]
        writable = model.getKeys(model.isWritablePoint)
        values = {}
        for key, value in call.data[ATTR_POINTS].items():
            if key not in writable:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="not_writable_point",
                    translation_placeholders={"point": key},
                )
            values[key] = point_value(model, key, value)
        await coordinator.async_write(model_id, 0, values)

    hass.services.async_register(DOMAIN, "write", write, schema=WRITE_SCHEMA)
