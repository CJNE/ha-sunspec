"""Recorder platform for SunSpec."""

from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .sensor import HA_META


@callback
def async_custom_equivalent_units(
    hass: HomeAssistant,
) -> dict[str, dict[str | None, str]]:
    """Return the SunSpec spelling of each unit a sensor shows renamed."""
    # Statistics recorded under a SunSpec spelling, such as Pct, continue under
    # the Home Assistant unit it is shown as, such as %.
    units = {
        sunspec: meta[0]
        for sunspec, meta in HA_META.items()
        if meta[0] and meta[0] != sunspec
    }
    return {
        entry.entity_id: units
        for entry in er.async_get(hass).entities.values()
        if entry.platform == DOMAIN and entry.domain == "sensor"
    }
