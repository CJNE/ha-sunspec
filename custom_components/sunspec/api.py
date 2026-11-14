"""Read SunSpec devices over Modbus with pysunspec2."""

import asyncio
from contextlib import asynccontextmanager
from functools import cache
import logging
from pathlib import Path
import socket
import time

from homeassistant.components.modbus import async_get_temporary_unit
from homeassistant.core import HomeAssistant
from modbus_connection import ModbusError
from modbus_connection import ModbusExceptionError
from modbus_connection import ModbusSerialParams
from modbus_connection import ModbusTcpParams
from modbus_connection import ModbusTimeoutError
from sunspec2 import mdef
from sunspec2.device import ModelError
from sunspec2.device import add_mappings
import sunspec2.modbus.client as modbus_client
from sunspec2.modbus.client import SunSpecModbusClientError
from sunspec2.modbus.modbus import REQ_COUNT_MAX
from sunspec2.smdx import from_smdx_file

from .const import CONF_BAUDRATE
from .const import CONF_DEVICE
from .const import CONF_HOST
from .const import CONF_PARITY
from .const import CONF_PORT
from .const import CONF_UNIT_ID
from .const import GROUP_NAMES

TIMEOUT = 120
# A serial bus stays silent for a unit ID that no device has, and the scan
# tries three base addresses. Home Assistant's Modbus integration waits three
# seconds.
SERIAL_TIMEOUT = 3

_LOGGER: logging.Logger = logging.getLogger(__package__)


class ConnectionError(Exception):
    pass


class ConnectionTimeoutError(ConnectionError):
    pass


class ModelRefusedError(Exception):
    """The device answered a model read with a Modbus exception."""


class NoSunSpecError(Exception):
    """The device has no SunSpec map at this unit ID."""


class SunSpecModelWrapper:
    def __init__(self, models) -> None:
        """Sunspec model wrapper"""
        self._models = models
        self.num_models = len(models)

    def isValidPoint(self, point_name):
        point = self.getPoint(point_name)
        if point.value is None:
            return False
        if point.pdef["type"] in ("enum16", "bitfield32"):
            return True
        if point.pdef.get("units", None) is None:
            return False
        return True

    def getKeys(self):
        keys = list(filter(self.isValidPoint, self._models[0].points.keys()))
        for group_name in self._models[0].groups:
            model_group = self._models[0].groups[group_name]
            if type(model_group) is list:
                for idx, group in enumerate(model_group):
                    key_prefix = f"{group_name}:{idx}"
                    group_keys = map(
                        lambda gp: f"{key_prefix}:{gp}", group.points.keys()
                    )
                    keys.extend(filter(self.isValidPoint, group_keys))
            else:
                key_prefix = f"{group_name}:0"
                group_keys = map(
                    lambda gp: f"{key_prefix}:{gp}", model_group.points.keys()
                )
                keys.extend(filter(self.isValidPoint, group_keys))
        return keys

    def getValue(self, point_name, model_index=0):
        point = self.getPoint(point_name, model_index)
        return point.cvalue

    def getMeta(self, point_name):
        return self.getPoint(point_name).pdef

    def getGroupMeta(self):
        gdef = self._models[0].gdef
        name = GROUP_NAMES.get(self._models[0].model_id)
        return {**gdef, "name": name} if name else gdef

    def getPoint(self, point_name, model_index=0):
        point_path = point_name.split(":")
        if len(point_path) == 1:
            return self._models[model_index].points[point_name]

        group = self._models[model_index].groups[point_path[0]]
        if type(group) is list:
            return group[int(point_path[1])].points[point_path[2]]
        else:
            if len(point_path) > 2:
                return group.points[
                    point_path[2]
                ]  # Access to the specific point within the group
            return group.points[
                point_name
            ]  # Generic access if no specific subgrouping is specified


# pragma: not covered
def progress(msg):
    _LOGGER.debug(msg)
    return True


def read_delay(client) -> float:
    """Return the pause before each model read."""
    common = client.models.get(1)
    # SMA asks for at least a second between Modbus transfers.
    if common and common[0].points["Mn"].value == "SMA":
        return 1
    return 0.6


@cache
def draft_definition(model_id):
    """Return SunSpec's 2015 definition of model 801, 802 or 803."""
    # github.com/sunspec/models e51bd84 (2015-09-29), Apache-2.0: see
    # models/LICENSE. pysunspec2 carries only today's definitions.
    definition = from_smdx_file(Path(__file__).parent / f"models/smdx_00{model_id}.xml")
    add_mappings(definition[mdef.GROUP])
    return definition


class DraftAwareModel(modbus_client.SunSpecModbusClientModel):
    """A model that, at a 2015 length, is read with its 2015 definition."""

    def __init__(self, model_id=None, model_len=0, model_def=None, **kwargs):
        # The E3DC S10 serves 801, 802 and 803 with 22, 20 and 16 plus 16 per
        # string registers, as defined in 2015. Today they have 1, 62 and 26
        # plus 32 per string, so a length tells the two apart.
        if (model_id, model_len) in ((801, 22), (802, 20)) or (
            model_id == 803 and model_len % 16 == 0
        ):
            model_def = draft_definition(model_id).copy()
        super().__init__(
            model_id=model_id, model_len=model_len, model_def=model_def, **kwargs
        )


def modbus_link(data):
    """Return the Modbus link and unit ID that connection settings describe."""
    if data.get(CONF_DEVICE):
        params = ModbusSerialParams(
            device=data[CONF_DEVICE],
            baudrate=data[CONF_BAUDRATE],
            parity=data[CONF_PARITY],
        )
    else:
        params = ModbusTcpParams(host=data[CONF_HOST], port=data[CONF_PORT])
    return params, data.get(CONF_UNIT_ID, 1)


@asynccontextmanager
async def temporary_client(hass: HomeAssistant, data):
    """Yield a client on a unit held only for the context, as flows need."""
    async with async_get_temporary_unit(hass, *modbus_link(data)) as unit:
        yield SunSpecApiClient(hass, data, unit)


class UnitDevice(modbus_client.SunSpecModbusClientDevice):
    """A pysunspec2 device that reads through a Home Assistant Modbus unit."""

    def __init__(self, hass: HomeAssistant, unit) -> None:
        super().__init__(model_class=DraftAwareModel)
        self._hass = hass
        self._unit = unit

    def read(self, addr, count):
        """Return the registers as bytes, read in requests Modbus allows."""
        start, end = int(addr), int(addr + count)
        registers = []
        for address in range(start, end, REQ_COUNT_MAX):
            registers += asyncio.run_coroutine_threadsafe(
                self._unit.read_holding_registers(
                    address, min(REQ_COUNT_MAX, end - address)
                ),
                self._hass.loop,
            ).result()
        return b"".join(register.to_bytes(2, "big") for register in registers)


class SunSpecApiClient:
    def __init__(self, hass: HomeAssistant, data, unit) -> None:
        """Sunspec client on a unit of Home Assistant's Modbus connection."""
        self._hass = hass
        self._unit = unit
        connection = data.get(CONF_DEVICE) or f"{data[CONF_HOST]}:{data[CONF_PORT]}"
        self._target = f"{connection} unit id {data.get(CONF_UNIT_ID, 1)}"
        self._address = (
            None if data.get(CONF_DEVICE) else (data[CONF_HOST], data[CONF_PORT])
        )
        unit.require_timeout(SERIAL_TIMEOUT if data.get(CONF_DEVICE) else TIMEOUT)
        self._client = None

    def get_client(self):
        if self._client is None:
            self._client = self.scan()
        return self._client

    def scan(self):
        """Return the device with the models the scan found."""
        if self._address and not self._unit.connected:
            # The scan tries three base addresses whatever fails, so a device
            # that is off would take three connection attempts. One quick one
            # fails it at once. Some SolarEdge inverters reset a connection
            # that follows another too closely (#321).
            try:
                with socket.create_connection(self._address, timeout=3):
                    pass
            except OSError as err:
                raise ConnectionError(f"Failed to connect to {self._target}") from err
            time.sleep(0.1)
        client = UnitDevice(self._hass, self._unit)
        try:
            try:
                client.scan(
                    connect=False,
                    progress=progress,
                    full_model_read=False,
                    delay=0.5,
                )
            except (ModbusExceptionError, ModelError) as err:
                if not client.models:
                    raise
                _LOGGER.warning("Scan stopped early, using the models found: %s", err)
        except ModbusTimeoutError as err:
            raise ConnectionTimeoutError(f"Timed out reading {self._target}") from err
        except ModbusError as err:
            raise ConnectionError(f"Failed to connect to {self._target}") from err
        except SunSpecModbusClientError as err:
            # The scan found no SunSpec map at any base address, or could not
            # reach the device to look.
            if not self._unit.connected:
                raise ConnectionError(f"Failed to connect to {self._target}") from err
            raise NoSunSpecError(f"No SunSpec data at {self._target}") from err
        return client

    async def async_get_data(self, model_id) -> SunSpecModelWrapper:
        try:
            _LOGGER.debug("Get data for model %s", model_id)
            return await self.read(model_id)
        except ModbusTimeoutError as err:
            raise ConnectionTimeoutError(err) from err
        except ModbusExceptionError as err:
            raise ModelRefusedError(err) from err
        except ModbusError as err:
            raise ConnectionError(err) from err

    async def read(self, model_id) -> SunSpecModelWrapper:
        return await self._hass.async_add_executor_job(self.read_model, model_id)

    async def async_get_device_info(self) -> SunSpecModelWrapper:
        return await self.read(1)

    def get_models(self) -> list:
        client = self.get_client()
        return sorted(list(filter(lambda m: type(m) is int, client.models.keys())))

    async def async_get_models(self) -> list:
        _LOGGER.debug("Fetching models")
        return await self._hass.async_add_executor_job(self.get_models)

    def read_model(self, model_id) -> dict:
        client = self.get_client()
        models = client.models[model_id]
        for model in models:
            time.sleep(read_delay(client))
            model.read()

        return SunSpecModelWrapper(models)
