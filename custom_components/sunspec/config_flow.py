"""Adds config flow for SunSpec."""
import logging

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .api import SunSpecApiClient
from .const import CONF_ENABLED_MODELS
from .const import CONF_HOST
from .const import CONF_PORT
from .const import CONF_SLAVE_ID
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
                return self.async_create_entry(title="", data=user_input)

            self._errors["base"] = "connection"

            return await self._show_config_form(user_input)

        return await self._show_config_form(user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SunSpecOptionsFlowHandler(config_entry)

    async def _show_config_form(self, user_input):  # pylint: disable=unused-argument
        """Show the configuration form to edit location data."""
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_PORT, default=502): int,
                    vol.Required(CONF_SLAVE_ID, default=1): int,
                }
            ),
            errors=self._errors,
        )

    async def _test_connection(self, host, port, slave_id):
        """Return true if credentials is valid."""
        try:
            client = SunSpecApiClient(host, port, slave_id, self.hass)
            self._device_info = await client.async_get_device_info()
            _LOGGER.info(self._device_info)
            return True
        except Exception as e:  # pylint: disable=broad-except
            _LOGGER.error("Failed to connect to host %s:%s - %s", host, port, e)
            pass
        return False


class SunSpecOptionsFlowHandler(config_entries.OptionsFlow):
    """Config flow options handler for sunspec."""

    def __init__(self, config_entry):
        """Initialize HACS options flow."""
        self.config_entry = config_entry
        self.options = dict(config_entry.options)
        self.coordinator = None

    async def async_step_init(self, user_input=None):  # pylint: disable=unused-argument
        """Manage the options."""
        self.coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]
        return await self.async_step_model_options()

    async def async_step_model_options(self, user_input=None):
        """Handle a flow initialized by the user."""
        if user_input is not None:
            self.options.update(user_input)
            return await self._update_options()

        models = set(await self.coordinator.api.async_get_models())
        model_filter = {str(model): str(model) for model in sorted(models)}
        return self.async_show_form(
            step_id="model_options",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ENABLED_MODELS,
                        default=self.coordinator.option_model_filter,
                    ): cv.multi_select(model_filter),
                }
            ),
        )

    async def _update_options(self):
        """Update config entry options."""
        return self.async_create_entry(title="", data=self.options)
