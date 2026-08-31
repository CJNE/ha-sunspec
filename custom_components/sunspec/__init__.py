"""
Custom integration to integrate SunSpec with Home Assistant.

For more details about this integration, please refer to
https://github.com/cjne/ha-sunspec
"""

import asyncio
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.core_config import Config
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import SunSpecApiClient
from .const import CONF_ENABLED_MODELS
from .const import CONF_HOST
from .const import CONF_PORT
from .const import CONF_SCAN_INTERVAL
from .const import CONF_UNIT_ID
from .const import DEFAULT_MODELS
from .const import DOMAIN
from .const import PLATFORMS
from .const import STARTUP_MESSAGE

SCAN_INTERVAL = timedelta(seconds=30)

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup(hass: HomeAssistant, config: Config):
    """Set up this integration using YAML is not supported."""
    return True


async def async_migrate_entry(hass, config_entry: ConfigEntry):
    """Migrate old entry."""
    _LOGGER.debug("Migrating configuration from version %s", config_entry.version)

    if config_entry.version == 1:
        # Migrate from version 1 to version 2
        # Version 1 used 'slave_id', version 2 uses 'unit_id'
        new_data = {**config_entry.data}

        # Migrate slave_id to unit_id if needed
        if "slave_id" in new_data:
            if "unit_id" not in new_data:
                # No unit_id exists, migrate slave_id to unit_id
                new_data["unit_id"] = new_data.pop("slave_id")
                _LOGGER.info(
                    "Migrated 'slave_id' to 'unit_id': %s", new_data["unit_id"]
                )
            else:
                # Both exist, remove slave_id and keep unit_id
                new_data.pop("slave_id")
                _LOGGER.info(
                    "Removed 'slave_id', keeping existing 'unit_id': %s",
                    new_data["unit_id"],
                )

        # Update the config entry with new version and data
        hass.config_entries.async_update_entry(config_entry, data=new_data, version=2)
        _LOGGER.info("Migration to version %s successful", config_entry.version)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up this integration using UI."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.info(STARTUP_MESSAGE)

    host = entry.data.get(CONF_HOST)
    port = entry.data.get(CONF_PORT)
    unit_id = entry.data.get(CONF_UNIT_ID, 1)

    client = SunSpecApiClient(host, port, unit_id, hass)

    _LOGGER.debug("Setup conifg entry for SunSpec")
    coordinator = SunSpecDataUpdateCoordinator(hass, client=client, entry=entry)
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
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
        coordinator.cancel_retry()
        coordinator.unsub()

    return True  # unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


def get_sunspec_unique_id(
    config_entry_id: str, key: str, model_id: int, model_index: int
) -> str:
    """Create a uniqe id for a SunSpec entity"""
    return f"{config_entry_id}_{key}-{model_id}-{model_index}"


class SunSpecDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    # Retry delays (seconds) after consecutive failures: 30 s, 60 s, 120 s,
    # then capped at 300 s for all subsequent attempts.  These fire in addition
    # to the normal scan_interval so recovery is fast even when scan_interval
    # is long (e.g. 5 minutes).
    _RETRY_DELAYS = (30, 60, 120, 300)

    def __init__(self, hass: HomeAssistant, client: SunSpecApiClient, entry) -> None:
        """Initialize."""
        self.api = client
        self.hass = hass
        self.entry = entry
        self._consecutive_failures = 0
        # Cancellation handle for a pending async_call_later retry; None when
        # no retry is scheduled.
        self._retry_unsub = None

        _LOGGER.debug("Data: %s", entry.data)
        _LOGGER.debug("Options: %s", entry.options)
        models = entry.options.get(
            CONF_ENABLED_MODELS, entry.data.get(CONF_ENABLED_MODELS, DEFAULT_MODELS)
        )
        scan_interval = timedelta(
            seconds=entry.options.get(
                CONF_SCAN_INTERVAL,
                entry.data.get(CONF_SCAN_INTERVAL, SCAN_INTERVAL.total_seconds()),
            )
        )
        self.option_model_filter = set(map(lambda m: int(m), models))
        self.unsub = entry.add_update_listener(async_reload_entry)
        _LOGGER.debug(
            "Setup entry with models %s, scan interval %s. IP: %s Port: %s ID: %s",
            self.option_model_filter,
            scan_interval,
            entry.data.get(CONF_HOST),
            entry.data.get(CONF_PORT),
            entry.data.get(CONF_UNIT_ID),
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=scan_interval,
            config_entry=entry,
        )

    def cancel_retry(self):
        """Cancel any pending exponential-backoff retry timer."""
        if self._retry_unsub is not None:
            self._retry_unsub()
            self._retry_unsub = None

    def _schedule_retry(self):
        """Schedule a one-shot reconnect attempt using exponential backoff.

        Only one retry can be pending at a time; subsequent failures while a
        retry is already queued are ignored — the queued retry will trigger
        async_request_refresh() which will either succeed or schedule the next
        one.
        """
        if self._retry_unsub is not None:
            return
        idx = min(self._consecutive_failures - 1, len(self._RETRY_DELAYS) - 1)
        delay = self._RETRY_DELAYS[idx]
        _LOGGER.info(
            "SunSpec scheduling reconnect retry in %ds (attempt #%d)",
            delay,
            self._consecutive_failures,
        )
        self._retry_unsub = async_call_later(self.hass, delay, self._async_retry_cb)

    async def _async_retry_cb(self, _now):
        """Fired by async_call_later; clears the handle then requests a refresh."""
        self._retry_unsub = None
        await self.async_request_refresh()

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("SunSpec Update data coordinator update")
        data = {}
        try:
            model_ids = self.option_model_filter & set(
                await self.api.async_get_models()
            )
            _LOGGER.debug("SunSpec Update data got models %s", model_ids)

            for model_id in model_ids:
                data[model_id] = await self.api.async_get_data(model_id)
            # Close the TCP connection after each successful poll; pysunspec2
            # will re-open it on the next read, keeping connections short-lived.
            self.api.close()
            if self._consecutive_failures > 0:
                _LOGGER.info(
                    "SunSpec connection restored after %d failure(s)",
                    self._consecutive_failures,
                )
            self._consecutive_failures = 0
            self.cancel_retry()
            return data
        except Exception as exception:
            _LOGGER.warning("SunSpec update failed: %s", exception)
            self._consecutive_failures += 1
            # Mark the API client so the next get_client() call performs a full
            # modbus_connect() + model scan instead of reusing the stale client.
            self.api.reconnect_next()
            self._schedule_retry()
            raise UpdateFailed() from exception
