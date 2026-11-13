"""Adds config flow for SunSpec."""

import logging

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from . import SCAN_INTERVAL
from . import api_client
from .api import ConnectionError
from .api import ConnectionTimeoutError
from .const import CONF_BAUDRATE
from .const import CONF_DEVICE
from .const import CONF_ENABLED_MODELS
from .const import CONF_HOST
from .const import CONF_MODEL_INTERVALS
from .const import CONF_PARITY
from .const import CONF_PORT
from .const import CONF_PREFIX
from .const import CONF_SCAN_INTERVAL
from .const import CONF_UNIT_ID
from .const import DEFAULT_MODELS
from .const import DOMAIN

_LOGGER: logging.Logger = logging.getLogger(__package__)


def entry_title(data):
    """Return the host, port and unit ID, or the serial port and unit ID."""
    if data.get(CONF_DEVICE):
        return f"{data[CONF_DEVICE]}:{data[CONF_UNIT_ID]}"
    return f"{data[CONF_HOST]}:{data[CONF_PORT]}:{data[CONF_UNIT_ID]}"


def serial_schema(data):
    """Return the serial connection form, filled in from data."""
    return vol.Schema(
        {
            vol.Required(
                CONF_DEVICE, default=data.get(CONF_DEVICE, "/dev/ttyUSB0")
            ): str,
            vol.Required(CONF_BAUDRATE, default=data.get(CONF_BAUDRATE, 9600)): int,
            # pysunspec2 sends 8 data bits and 1 stop bit, with no or even parity.
            vol.Required(CONF_PARITY, default=data.get(CONF_PARITY, "N")): vol.In(
                {"N": "None", "E": "Even"}
            ),
            vol.Required(CONF_UNIT_ID, default=data.get(CONF_UNIT_ID, 1)): int,
        }
    )


def set_connection_error(errors, target, err):
    """Map backend failures to user-visible config flow errors."""
    if isinstance(err, ConnectionTimeoutError):
        errors["base"] = "timeout"
        _LOGGER.warning("Timeout while connecting to %s", target)
        return

    if isinstance(err, ConnectionError):
        errors["base"] = "connection"
        _LOGGER.warning("Connection failed for %s: %s", target, err)
        return

    errors["base"] = "device_error"
    _LOGGER.exception("Unexpected error while connecting to %s", target, exc_info=err)


class SunSpecFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for sunspec."""

    VERSION = 2

    def __init__(self):
        """Initialize."""
        self._errors = {}

    def _get_unique_id(self, fallback_uid):
        """Build a stable unique ID even when device serial data is missing."""
        try:
            uid = self._device_info.getValue("SN")
        except KeyError:
            uid = None

        if uid in (None, ""):
            _LOGGER.info(
                "Device did not provide serial number during setup, using %s as unique ID",
                fallback_uid,
            )
            return fallback_uid

        return str(uid)

    async def async_step_user(self, user_input=None):
        """Ask how the device is connected."""
        return self.async_show_menu(step_id="user", menu_options=["tcp", "serial"])

    async def async_step_tcp(self, user_input=None):
        """Handle a Modbus TCP connection."""
        self._errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            unit_id = user_input.get(CONF_UNIT_ID) or user_input.get("slave_id", 1)
            connection = {CONF_HOST: host, CONF_PORT: port, CONF_UNIT_ID: unit_id}
            if await self._test_connection(connection):
                return await self._add_device(connection, user_input)

            return await self._show_config_form(user_input)

        return await self._show_config_form(user_input)

    async def async_step_serial(self, user_input=None):
        """Handle a Modbus RTU connection on a serial port."""
        self._errors = {}
        if user_input is not None and await self._test_connection(user_input):
            return await self._add_device(user_input, user_input)

        return self.async_show_form(
            step_id="serial",
            data_schema=serial_schema(user_input or {}),
            errors=self._errors,
        )

    async def _add_device(self, connection, user_input):
        """Continue with the settings of a device that answered."""
        uid = self._get_unique_id(entry_title(connection))
        _LOGGER.debug(f"Sunspec device unique id: {uid}")
        await self.async_set_unique_id(uid)

        # Adding a configured device again moves it to this connection.
        self._abort_if_unique_id_configured(updates={CONF_DEVICE: None, **connection})
        self.init_info = user_input
        return await self.async_step_settings()

    async def async_step_settings(self, user_input=None):
        self._errors = {}
        if user_input is not None:
            self.init_info[CONF_PREFIX] = user_input[CONF_PREFIX]
            self.init_info[CONF_ENABLED_MODELS] = user_input[CONF_ENABLED_MODELS]
            self.init_info[CONF_SCAN_INTERVAL] = user_input[CONF_SCAN_INTERVAL]
            _LOGGER.debug("Creating entry with data %s", self.init_info)
            return self.async_create_entry(
                title=entry_title(self.init_info), data=self.init_info
            )

        return await self._show_settings_form(user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SunSpecOptionsFlowHandler()

    async def _show_config_form(self, user_input):
        """Show the configuration form to edit connection data."""
        defaults = user_input or {CONF_HOST: "", CONF_PORT: 502, CONF_UNIT_ID: 1}
        return self.async_show_form(
            step_id="tcp",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=defaults[CONF_HOST]): str,
                    vol.Required(CONF_PORT, default=defaults[CONF_PORT]): int,
                    vol.Required(CONF_UNIT_ID, default=defaults[CONF_UNIT_ID]): int,
                }
            ),
            errors=self._errors,
        )

    async def _show_settings_form(self, user_input):
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

    async def _test_connection(self, connection):
        """Return true if the device answers on the connection."""
        _LOGGER.debug(f"Test connection to {entry_title(connection)}")
        try:
            self.client = api_client(self.hass, connection)
            self._device_info = await self.client.async_get_device_info()
            _LOGGER.info(self._device_info)
            return True
        except Exception as err:
            set_connection_error(self._errors, entry_title(connection), err)
        return False


class SunSpecOptionsFlowHandler(config_entries.OptionsFlow):
    """Config flow options handler for sunspec."""

    VERSION = 1

    def __init__(self):
        """Initialize options flow."""
        self._errors = {}
        self.settings = {}
        self.options = {}
        self.coordinator = None

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        self._errors = {}
        self.options = dict(self.config_entry.options)
        self.coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]
        return await self.async_step_host_options()

    async def async_step_host_options(self, user_input=None):
        """Handle a flow initialized by the user."""
        if user_input is not None:
            self.settings.update(user_input)
            _LOGGER.debug("Sunspec host setttins: %s", user_input)
            return await self.async_step_model_options()

        return await self.show_settings_form()

    async def async_step_serial_options(self, user_input=None):
        """Handle the serial connection settings."""
        return await self.async_step_host_options(user_input)

    async def show_settings_form(self, data=None, errors=None):
        settings = data or self.config_entry.data
        if settings.get(CONF_DEVICE):
            return self.async_show_form(
                step_id="serial_options",
                data_schema=serial_schema(settings),
                errors=errors,
            )
        host = settings.get(CONF_HOST)
        port = settings.get(CONF_PORT)
        unit_id = settings.get(CONF_UNIT_ID) or settings.get("slave_id", 1)

        return self.async_show_form(
            step_id="host_options",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=host): str,
                    vol.Required(CONF_PORT, default=port): int,
                    vol.Required(CONF_UNIT_ID, default=unit_id): int,
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
        intervals = self.config_entry.options.get(CONF_MODEL_INTERVALS, {})
        connection = {key: self.config_entry.data.get(key) for key in self.settings}
        try:
            # The entry's connection serves unchanged settings: a device with one
            # Modbus TCP slot refuses a second connection while the entry polls.
            config = None if self.settings == connection else self.settings
            models = set(await self.coordinator.api.async_get_models(config))
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
                        vol.Optional(CONF_MODEL_INTERVALS, default={}): section(
                            vol.Schema(
                                {
                                    vol.Optional(
                                        str(model),
                                        description={
                                            "suggested_value": intervals.get(str(model))
                                        },
                                    ): vol.All(int, vol.Range(min=1))
                                    for model in model_filter
                                }
                            ),
                            {"collapsed": True},
                        ),
                    }
                ),
            )
        except Exception as e:
            set_connection_error(self._errors, entry_title(self.settings), e)
            return await self.show_settings_form(
                data=self.settings, errors=self._errors
            )

    async def _update_options(self):
        """Update config entry options."""
        title = entry_title(self.settings)
        _LOGGER.debug(
            "Saving config entry with title %s, data: %s options %s",
            title,
            self.settings,
            self.options,
        )
        if self.hass.config_entries.async_update_entry(
            self.config_entry, data=self.settings, options=self.options, title=title
        ):
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
        return self.async_create_entry(title="", data=self.options)
