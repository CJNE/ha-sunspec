"""SunSpecEntity class"""
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION
from .const import DOMAIN
from .const import NAME
from .const import VERSION


class SunSpecEntity(CoordinatorEntity):
    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator)
        self.config_entry = config_entry


