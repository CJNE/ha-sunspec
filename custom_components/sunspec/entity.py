"""SunSpecEntity class"""

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class SunSpecEntity(CoordinatorEntity):
    def __init__(self, coordinator, config_entry, device_info, model_info):
        super().__init__(coordinator)
        self._device_data = device_info
        self.config_entry = config_entry
        self.model_info = model_info

    # @property
    # def unique_id(self):
    #    """Return a unique ID to use for this entity."""
    #    return self.config_entry.entry_id

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
