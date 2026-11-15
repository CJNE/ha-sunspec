"""Number platform for SunSpec."""

from homeassistant.components.number import NumberEntity

from .const import NUMBER
from .entity import SunSpecControlEntity
from .entity import async_add_write_entities
from .sensor import HA_META


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up a number for each writable point that takes a number."""
    async_add_write_entities(
        hass,
        entry,
        async_add_entities,
        NUMBER,
        lambda coordinator, entry, data: [SunSpecNumber(coordinator, entry, data)],
    )


class SunSpecNumber(SunSpecControlEntity, NumberEntity):
    """A number that writes its point in the point's units."""

    def __init__(self, coordinator, config_entry, data):
        super().__init__(coordinator, config_entry, data)
        units = self._meta.get("units")
        self._attr_native_unit_of_measurement = HA_META.get(units, [units])[0]

    @property
    def native_value(self):
        return self.point_value

    @property
    def native_min_value(self):
        return self.coordinator.data[self.model_id].getRange(
            self.key, self.model_index
        )[0]

    @property
    def native_max_value(self):
        return self.coordinator.data[self.model_id].getRange(
            self.key, self.model_index
        )[1]

    @property
    def native_step(self):
        return self.coordinator.data[self.model_id].getRange(
            self.key, self.model_index
        )[2]

    async def async_set_native_value(self, value):
        await self.async_write(value)
