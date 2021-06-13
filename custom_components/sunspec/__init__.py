"""
Custom integration to integrate SunSpec with Home Assistant.

For more details about this integration, please refer to
https://github.com/cjne/ha-sunspec
"""
import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Config
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import SunSpecApiClient
from .const import CONF_ENABLED_MODELS
from .const import CONF_HOST
from .const import CONF_PORT
from .const import CONF_SLAVE_ID
from .const import DEFAULT_MODELS
from .const import DOMAIN
from .const import PLATFORMS
from .const import STARTUP_MESSAGE

SCAN_INTERVAL = timedelta(seconds=30)

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup(hass: HomeAssistant, config: Config):
    """Set up this integration using YAML is not supported."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up this integration using UI."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.info(STARTUP_MESSAGE)

    host = entry.data.get(CONF_HOST)
    port = entry.data.get(CONF_PORT)
    slave_id = entry.data.get(CONF_SLAVE_ID, 1)

    models = entry.options.get(
        CONF_ENABLED_MODELS, entry.data.get(CONF_ENABLED_MODELS, DEFAULT_MODELS)
    )
    _LOGGER.debug("Setup entry with models %s", models)

    client = SunSpecApiClient(host, port, slave_id, hass)

    unsub = entry.add_update_listener(async_reload_entry)

    coordinator = SunSpecDataUpdateCoordinator(
        hass, client=client, models=models, unsub=unsub
    )
    await coordinator.async_refresh()

    if not coordinator.last_update_success:
        raise ConfigEntryNotReady

    hass.data[DOMAIN][entry.entry_id] = coordinator

    for platform in PLATFORMS:
        hass.async_add_job(
            hass.config_entries.async_forward_entry_setup(entry, platform)
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""

    _LOGGER.debug("Unload entry")
    unloaded = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in PLATFORMS
            ]
        )
    )
    if unloaded:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator.unsub()

    return True  # unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


class SunSpecDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(
        self, hass: HomeAssistant, client: SunSpecApiClient, models: list, unsub
    ) -> None:
        """Initialize."""
        self.api = client
        self.option_model_filter = set(map(lambda m: int(m), models))
        self.unsub = unsub
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL)

    async def _async_update_data(self):
        """Update data via library."""
        data = {}
        model_ids = self.option_model_filter & set(await self.api.async_get_models())
        try:
            for model_id in model_ids:
                data[model_id] = await self.api.async_get_data(model_id)
            self.api.close()
            return data
        except Exception as exception:
            _LOGGER.error(exception)
            self.api.reconnect()
            raise UpdateFailed() from exception
