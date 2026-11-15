"""Select platform for SunSpec."""

from homeassistant.components.select import SelectEntity

from .const import SELECT
from .entity import SunSpecControlEntity
from .entity import async_add_write_entities


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up a select for each writable enum point but on/off ones."""
    async_add_write_entities(
        hass,
        entry,
        async_add_entities,
        SELECT,
        lambda coordinator, entry, data: [SunSpecSelect(coordinator, entry, data)],
    )


class SunSpecSelect(SunSpecControlEntity, SelectEntity):
    """A select that writes its point's symbol."""

    def __init__(self, coordinator, config_entry, data):
        super().__init__(coordinator, config_entry, data)
        self._symbols = {
            symbol["name"]: symbol["value"] for symbol in self._meta["symbols"]
        }
        self._attr_options = list(self._symbols)

    @property
    def current_option(self):
        return next(
            (
                name
                for name, value in self._symbols.items()
                if value == self.point_value
            ),
            None,
        )

    async def async_select_option(self, option):
        await self.async_write(self._symbols[option])
