"""
Custom integration to integrate SunSpec with Home Assistant.

For more details about this integration, please refer to
https://github.com/cjne/ha-sunspec
"""

import asyncio
from datetime import timedelta
import logging
from time import monotonic

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import ConnectionError
from .api import ModelMovedError
from .api import ModelRefusedError
from .api import SunSpecApiClient
from .const import CONF_ALLOW_WRITING
from .const import CONF_BAUDRATE
from .const import CONF_DEVICE
from .const import CONF_ENABLED_MODELS
from .const import CONF_HOST
from .const import CONF_MODEL_INTERVALS
from .const import CONF_PARITY
from .const import CONF_PORT
from .const import CONF_SCAN_INTERVAL
from .const import CONF_UNIT_ID
from .const import DEFAULT_MODELS
from .const import DOMAIN
from .const import NUMBER
from .const import PLATFORMS
from .const import SELECT
from .const import SWITCH
from .services import async_setup_services

SCAN_INTERVAL = timedelta(seconds=30)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the write action, also while no entry is loaded."""
    async_setup_services(hass)
    return True


def api_client(hass: HomeAssistant, data) -> SunSpecApiClient:
    """Return the API client for an entry's connection settings."""
    return SunSpecApiClient(
        data.get(CONF_HOST),
        data.get(CONF_PORT),
        data.get(CONF_UNIT_ID, 1),
        hass,
        data.get(CONF_DEVICE),
        data.get(CONF_BAUDRATE),
        data.get(CONF_PARITY),
    )


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
    hass.data.setdefault(DOMAIN, {})

    client = api_client(hass, entry.data)

    _LOGGER.debug("Setup conifg entry for SunSpec")
    coordinator = SunSpecDataUpdateCoordinator(hass, client=client, entry=entry)
    hass.data[DOMAIN][entry.entry_id] = coordinator

    if not entry.options.get(CONF_ALLOW_WRITING):
        # Writing turned off takes the write entities with it.
        registry = er.async_get(hass)
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
            if entity.domain in (NUMBER, SELECT, SWITCH):
                registry.async_remove(entity.entity_id)

    # The first refresh scans the device, which can take long or time out, so
    # it runs in the background instead of holding up Home Assistant's start.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(
        hass, coordinator.async_refresh(), f"{DOMAIN} first refresh"
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
        hass.data[DOMAIN].pop(entry.entry_id)

    return True  # unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Close a removed entry's connection, which a device may allow only one of."""
    client = api_client(hass, entry.data)
    await hass.async_add_executor_job(client.disconnect)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow removing a device once the entry no longer reads its model."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None or not coordinator.data:
        return False
    names = {model.getGroupMeta()["name"] for model in coordinator.data.values()}
    return not any(
        identifier[2] in names
        for identifier in device.identifiers
        if identifier[0] == DOMAIN
    )


def get_sunspec_unique_id(
    config_entry_id: str, key: str, model_id: int, model_index: int
) -> str:
    """Create a uniqe id for a SunSpec entity"""
    return f"{config_entry_id}_{key}-{model_id}-{model_index}"


class SunSpecDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(self, hass: HomeAssistant, client: SunSpecApiClient, entry) -> None:
        """Initialize."""
        self.api = client
        self.hass = hass
        self.entry = entry

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
        intervals = entry.options.get(CONF_MODEL_INTERVALS, {})
        # Seconds between reads of each model: its own or the scan interval.
        self.model_intervals = {
            model: intervals.get(str(model), scan_interval.total_seconds())
            for model in self.option_model_filter
        }
        self.last_read = {}
        self.device_info = None
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
            update_interval=timedelta(
                seconds=min(
                    self.model_intervals.values(),
                    default=scan_interval.total_seconds(),
                )
            ),
            config_entry=entry,
        )

    async def _async_update_data(self):
        """Update data via library."""
        _LOGGER.debug("SunSpec Update data coordinator update")
        data = {}
        try:
            if self.device_info is None:
                self.device_info = await self.api.async_get_device_info()
            model_ids = self.option_model_filter & set(
                await self.api.async_get_models()
            )
            _LOGGER.debug("SunSpec Update data got models %s", model_ids)

            now = monotonic()
            poll = self.update_interval.total_seconds()
            for model_id in model_ids:
                interval = self.model_intervals[model_id]
                # A model slower than the polls is read at the poll nearest to
                # its interval. The others are read at every poll.
                if (
                    interval > poll
                    and model_id in self.last_read
                    and model_id in (self.data or {})
                    and now - self.last_read[model_id] < interval - poll / 2
                ):
                    data[model_id] = self.data[model_id]
                    continue
                try:
                    data[model_id] = await self.api.async_get_data(model_id)
                    self.last_read[model_id] = now
                except ModelRefusedError as err:
                    # The device answered but refused the model, as an SMA
                    # Sunny Tripower X does while it sleeps at night.
                    if model_id not in (self.data or {}):
                        raise
                    _LOGGER.debug(
                        "Keeping the last values of model %s: %s", model_id, err
                    )
                    data[model_id] = self.data[model_id]
            return data
        except Exception as exception:
            _LOGGER.warning(exception)
            self.api.reconnect_next()
            self.reload_if_moved(exception)
            raise UpdateFailed() from exception

    def reload_if_moved(self, err):
        """Set the entry up anew after the device moved a model."""
        # Its entities and their last reads belong to the models of the old scan.
        if isinstance(err, ModelMovedError):
            self.hass.config_entries.async_schedule_reload(self.entry.entry_id)

    async def async_write(self, model_id, model_index, values):
        """Write points of a model, then show what the device reports."""
        try:
            await self.api.async_write(model_id, model_index, values)
        except (ModelRefusedError, ConnectionError) as err:
            key = "write_refused"
            if isinstance(err, ConnectionError):
                # A late answer to the write must not be taken for the next one.
                self.api.reconnect_next()
                self.reload_if_moved(err)
                key = "write_failed"
            if self.api.unconfirmed.get((model_id, model_index)) is values:
                # It was sent: the next poll reads the model, whatever its interval.
                self.last_read.pop(model_id, None)
                key = "write_unconfirmed"
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=key,
                translation_placeholders={"error": str(err)},
            ) from err
        finally:
            self.async_update_listeners()
