"""SunSpecEntity class"""

from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import get_sunspec_unique_id
from .const import CONF_ALLOW_WRITING
from .const import CONF_PREFIX
from .const import DOMAIN
from .const import NUMBER
from .const import SELECT
from .const import SWITCH
from .const import WRITE_MODELS

ON_OFF = ({"DISABLED": 0, "ENABLED": 1}, {"OFF": 0, "ON": 1})


@callback
def async_add_point_entities(hass, entry, async_add_entities, keys, entities):
    """Add the entities of each point that keys gives, with its first value."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    prefix = entry.options.get(CONF_PREFIX, entry.data.get(CONF_PREFIX, ""))
    added = set()

    # A point gets its entities with its first value, which can come after
    # setup: a device reports "not implemented" for a point it cannot measure
    # yet, such as at night, the same as for a point it does not have.
    @callback
    def add_entities():
        if not coordinator.data:
            return
        new = []
        for model_id, model_wrapper in coordinator.data.items():
            for key in keys(model_id, model_wrapper):
                if (model_id, key) in added:
                    continue
                added.add((model_id, key))
                for model_index in range(model_wrapper.num_models):
                    data = {
                        "device_info": coordinator.device_info,
                        "key": key,
                        "model_id": model_id,
                        "model_index": model_index,
                        "model": model_wrapper,
                        "prefix": prefix,
                    }
                    new.extend(entities(coordinator, entry, data))
        if new:
            async_add_entities(new)

    add_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_entities))


def write_platform(meta):
    """Return the platform of the entity that writes a point."""
    symbols = {symbol["name"]: symbol["value"] for symbol in meta.get("symbols", [])}
    if meta["type"].startswith("bitfield") or symbols in ON_OFF:
        return SWITCH
    if meta["type"].startswith("enum"):
        return SELECT
    return NUMBER


@callback
def async_add_write_entities(hass, entry, async_add_entities, platform, entities):
    """Add the entities of a platform for writable points, if the entry writes."""
    if not entry.options.get(CONF_ALLOW_WRITING):
        return

    def keys(model_id, model_wrapper):
        if model_id not in WRITE_MODELS:
            return []
        return [
            key
            for key in model_wrapper.getKeys(model_wrapper.isWritablePoint)
            if write_platform(model_wrapper.getMeta(key)) == platform
        ]

    async_add_point_entities(hass, entry, async_add_entities, keys, entities)


class SunSpecEntity(CoordinatorEntity):
    def __init__(self, coordinator, config_entry, data):
        super().__init__(coordinator)
        self._device_data = data["device_info"]
        self.config_entry = config_entry
        self.model_id = data["model_id"]
        self.model_index = data["model_index"]
        self.model_wrapper = data["model"]
        self.model_info = self.model_wrapper.getGroupMeta()
        self.key = data["key"]
        self._meta = self.model_wrapper.getMeta(self.key)
        self._uniqe_id = get_sunspec_unique_id(
            config_entry.entry_id, self.key, self.model_id, self.model_index
        )

        name = self.model_info.get("name", str(self.model_id))
        if self.model_index > 0:
            name = f"{name} {self.model_index}"
        key_parts = self.key.split(":")
        if len(key_parts) > 1:
            name = f"{name} {key_parts[0]} {key_parts[1]}"
        if data["prefix"] != "":
            name = f"{data['prefix']} {name}"
        self._name = f"{name.capitalize()} {self._meta.get('label', self.key)}"

    @property
    def available(self):
        """Return whether the device was read since the point was written."""
        unconfirmed = self.coordinator.api.unconfirmed
        return super().available and self.key not in unconfirmed.get(
            (self.model_id, self.model_index), ()
        )

    @property
    def name(self):
        """Return the name of the entity."""
        return self._name

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return self._uniqe_id

    @property
    def device_info(self):
        return {
            "identifiers": {
                (DOMAIN, self.config_entry.entry_id, self.model_info["name"])
            },
            "name": self.model_info["label"],
            "model": self._device_data.getValue("Md"),
            "sw_version": self._device_data.getValue("Vr"),
            "manufacturer": self._device_data.getValue("Mn"),
        }

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        attrs = {
            "integration": DOMAIN,
            "sunspec_key": self.key,
        }
        label = self._meta.get("label", None)
        if label is not None:
            attrs["label"] = label

        vtype = self._meta["type"]
        if vtype in ("enum16", "bitfield32"):
            attrs["raw"] = self.coordinator.data[self.model_id].getValue(
                self.key, self.model_index
            )
        return attrs


class SunSpecControlEntity(SunSpecEntity):
    """An entity that writes its point to the device."""

    _attr_entity_category = EntityCategory.CONFIG

    @property
    def point_value(self):
        return self.coordinator.data[self.model_id].getValue(self.key, self.model_index)

    async def async_write(self, value):
        await self.coordinator.async_write(
            self.model_id, self.model_index, {self.key: value}
        )
