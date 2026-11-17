"""Switch platform for SunSpec."""

from homeassistant.components.switch import SwitchEntity

from . import get_sunspec_unique_id
from .const import SWITCH
from .entity import SunSpecControlEntity
from .entity import async_add_write_entities


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up a switch for each writable on/off point and bitfield bit."""
    async_add_write_entities(hass, entry, async_add_entities, SWITCH, switches)


def switches(coordinator, entry, data):
    """Return the switch of an on/off point, or one for each bit of a bitfield."""
    meta = data["model"].getMeta(data["key"], data["model_index"])
    if meta["type"].startswith("bitfield"):
        return [
            SunSpecBitSwitch(coordinator, entry, data, symbol)
            for symbol in meta["symbols"]
        ]
    return [SunSpecSwitch(coordinator, entry, data)]


class SunSpecSwitch(SunSpecControlEntity, SwitchEntity):
    """A switch that writes 1 for on and 0 for off."""

    @property
    def is_on(self):
        value = self.point_value
        return None if value is None else value == 1

    async def async_turn_on(self, **kwargs):
        await self.async_write(1)

    async def async_turn_off(self, **kwargs):
        await self.async_write(0)


class SunSpecBitSwitch(SunSpecControlEntity, SwitchEntity):
    """A switch for one bit of a bitfield, which can have several bits set."""

    def __init__(self, coordinator, config_entry, data, symbol):
        super().__init__(coordinator, config_entry, data)
        self._bit = 1 << symbol["value"]
        self._name = f"{self._name} {symbol['name']}"
        self._uniqe_id = get_sunspec_unique_id(
            config_entry.entry_id,
            f"{self.key}:{symbol['value']}",
            self.model_id,
            self.model_index,
        )

    @property
    def is_on(self):
        value = self.point_value
        return None if value is None else bool(value & self._bit)

    async def async_turn_on(self, **kwargs):
        await self.async_write(lambda value: value | self._bit)

    async def async_turn_off(self, **kwargs):
        await self.async_write(lambda value: value & ~self._bit)
