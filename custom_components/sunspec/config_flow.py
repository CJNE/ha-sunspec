"""Adds config flow for SunSpec."""

import logging

from homeassistant import config_entries
from homeassistant.core_config import callback
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from . import SCAN_INTERVAL
from .api import SunSpecApiClient
from .const import CONF_ENABLED_MODELS
from .const import CONF_HOST
from .const import CONF_PORT
from .const import CONF_PREFIX
from .const import CONF_SCAN_INTERVAL
from .const import CONF_SLAVE_ID
from .const import DEFAULT_MODELS
from .const import DOMAIN

_LOGGER: logging.Logger = logging.getLogger(__package__)


class SunSpecFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for sunspec."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self):
        """Initialize."""
        self._errors = {}

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        self._errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            slave_id = user_input[CONF_SLAVE_ID]
            valid = await self._test_connection(host, port, slave_id)
            if valid:
                uid = self._device_info.getValue("SN")
                _LOGGER.debug(f"Sunspec device unique id: {uid}")
                await self.async_set_unique_id(uid)

                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: host, CONF_PORT: port, CONF_SLAVE_ID: slave_id}
                )
                self.init_info = user_input
                return await self.async_step_settings()

                # return self.async_create_entry(title=f"{host}:{port}", data=user_input)

            self._errors["base"] = "connection"

            return await self._show_config_form(user_input)

        return await self._show_config_form(user_input)

    async def async_step_settings(self, user_input=None):
        self._errors = {}
        if user_input is not None:
            self.init_info[CONF_PREFIX] = user_input[CONF_PREFIX]
            self.init_info[CONF_ENABLED_MODELS] = user_input[CONF_ENABLED_MODELS]
            self.init_info[CONF_SCAN_INTERVAL] = user_input[CONF_SCAN_INTERVAL]
            host = self.init_info[CONF_HOST]
            port = self.init_info[CONF_PORT]
            slave_id = self.init_info[CONF_SLAVE_ID]
            _LOGGER.debug("Creating entry with data %s", self.init_info)
            return self.async_create_entry(
                title=f"{host}:{port}:{slave_id}", data=self.init_info
            )

        return await self._show_settings_form(user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SunSpecOptionsFlowHandler(config_entry)

    async def _show_config_form(self, user_input):  # pylint: disable=unused-argument
        """Show the configuration form to edit connection data."""
        defaults = user_input or {CONF_HOST: "", CONF_PORT: 502, CONF_SLAVE_ID: 1}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=defaults[CONF_HOST]): str,
                    vol.Required(CONF_PORT, default=defaults[CONF_PORT]): int,
                    vol.Required(CONF_SLAVE_ID, default=defaults[CONF_SLAVE_ID]): int,
                }
            ),
            errors=self._errors,
        )

    async def _show_settings_form(self, user_input):  # pylint: disable=unused-argument
        """Show the configuration form to edit settings data."""
        models = set(await self.client.async_get_models())
        model_filter = {model for model in sorted(models)}
        default_enabled = {model for model in DEFAULT_MODELS if model in models}
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_PREFIX, default=""): str,
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=SCAN_INTERVAL.total_seconds()
                    ): int,
                    vol.Optional(
                        CONF_ENABLED_MODELS,
                        default=default_enabled,
                    ): cv.multi_select(model_filter),
                }
            ),
            errors=self._errors,
        )

    async def _test_connection(self, host, port, slave_id):
        """Return true if credentials is valid."""
        _LOGGER.debug(f"Test connection to {host}:{port} slave id {slave_id}")
        try:
            self.client = SunSpecApiClient(host, port, slave_id, self.hass)
            self._device_info = await self.client.async_get_device_info()
            _LOGGER.info(self._device_info)
            return True
        except Exception as e:  # pylint: disable=broad-except
            _LOGGER.error(
                "Failed to connect to host %s:%s slave %s - %s", host, port, slave_id, e
            )
            pass
        return False


class SunSpecOptionsFlowHandler(config_entries.OptionsFlow):
    """Config flow options handler for sunspec."""

    VERSION = 1

    def __init__(self, config_entry):
        """Initialize HACS options flow."""
        self.config_entry = config_entry
        self.settings = {}
        self.options = dict(config_entry.options)
        self.coordinator = None

    async def async_step_init(self, user_input=None):  # pylint: disable=unused-argument
        """Manage the options."""
        self.coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]
        return await self.async_step_host_options()

    async def async_step_host_options(self, user_input=None):
        """Handle a flow initialized by the user."""
        if user_input is not None:
            self.settings.update(user_input)
            _LOGGER.debug("Sunspec host setttins: %s", user_input)
            return await self.async_step_model_options()

        return await self.show_settings_form()

    async def show_settings_form(self, data=None, errors=None):
        settings = data or self.config_entry.data
        host = settings.get(CONF_HOST)
        port = settings.get(CONF_PORT)
        slave_id = settings.get(CONF_SLAVE_ID)

        return self.async_show_form(
            step_id="host_options",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=host): str,
                    vol.Required(CONF_PORT, default=port): int,
                    vol.Required(CONF_SLAVE_ID, default=slave_id): int,
                }
            ),
            errors=errors,
        )

    async def async_step_model_options(self, user_input=None):
        """Handle a flow initialized by the user."""
        if user_input is not None:
            self.options.update(user_input)
            return await self._update_options()

        prefix = self.config_entry.options.get(
            CONF_PREFIX, self.config_entry.data.get(CONF_PREFIX)
        )
        scan_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, self.config_entry.data.get(CONF_SCAN_INTERVAL)
        )
        try:
            models = set(await self.coordinator.api.async_get_models(self.settings))
            model_filter = {model for model in sorted(models)}
            default_enabled = {model for model in DEFAULT_MODELS if model in models}
            default_models = self.config_entry.options.get(
                CONF_ENABLED_MODELS, default_enabled
            )

            default_models = {model for model in default_models if model in models}

            return self.async_show_form(
                step_id="model_options",
                data_schema=vol.Schema(
                    {
                        vol.Optional(CONF_PREFIX, default=prefix): str,
                        vol.Optional(CONF_SCAN_INTERVAL, default=scan_interval): int,
                        vol.Optional(
                            CONF_ENABLED_MODELS,
                            default=default_models,
                        ): cv.multi_select(model_filter),
                    }
                ),
            )
        except Exception as e:  # pylint: disable=broad-except
            _LOGGER.error(
                "Failed to connect to host %s:%s slave %s - %s",
                self.settings[CONF_HOST],
                self.settings[CONF_PORT],
                self.settings[CONF_SLAVE_ID],
                e,
            )
            return await self.show_settings_form(
                data=self.settings, errors={"base": "connection"}
            )

    async def _update_options(self):
        """Update config entry options."""
        # self.settings[CONF_PORT] = 503
        # self.settings[CONF_ENABLED_MODELS] = [160, 103]
        title = f"{self.settings[CONF_HOST]}:{self.settings[CONF_PORT]}:{self.settings[CONF_SLAVE_ID]}"
        _LOGGER.debug(
            "Saving config entry with title %s, data: %s options %s",
            title,
            self.settings,
            self.options,
        )
        self.hass.config_entries.async_update_entry(
            self.config_entry, data=self.settings, title=title
        )
        return self.async_create_entry(title="", data=self.options)
