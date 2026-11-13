"""Sample API Client."""

import logging
import select
import socket
import threading
import time
from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from sunspec2.device import ModelError
import sunspec2.modbus.client as modbus_client
from sunspec2.modbus.client import SunSpecModbusClientException
from sunspec2.modbus.client import SunSpecModbusClientTimeout
from sunspec2.modbus.modbus import ModbusClientError
from sunspec2.modbus.modbus import ModbusClientException

from .const import GROUP_NAMES

TIMEOUT = 120

_LOGGER: logging.Logger = logging.getLogger(__package__)


class ConnectionTimeoutError(Exception):
    pass


class ConnectionError(Exception):
    pass


class ModelRefusedError(Exception):
    """The device answered a model read with a Modbus exception."""


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


def closed_by_device(client) -> bool:
    """Return True if the device closed the connection between requests."""
    sock = client.client.socket
    if sock is None:
        return False
    # No answer is due between requests, so a readable socket means the device
    # closed the connection or sent something nobody asked for. poll() takes
    # any file descriptor, select() only those below 1024.
    poller = select.poll()
    poller.register(sock, select.POLLIN)
    return bool(poller.poll(0))


def read_delay(client) -> float:
    """Return the pause before each model read."""
    common = client.models.get(1)
    # SMA asks for at least a second between Modbus transfers.
    if common and common[0].points["Mn"].value == "SMA":
        return 1
    return 0.6


class SunSpecApiClient:
    CLIENT_CACHE = {}
    LOCKS = {}

    def __init__(self, host: str, port: int, unit_id: int, hass: HomeAssistant) -> None:
        """Sunspec modbus client."""

        _LOGGER.debug("New SunspecApi Client")
        self._host = host
        self._port = port
        self._hass = hass
        self._unit_id = unit_id
        self._client_key = f"{host}:{port}:{unit_id}"
        # Entries on one host and port share its connection and take turns.
        self._lock = SunSpecApiClient.LOCKS.setdefault(
            f"{host}:{port}", threading.RLock()
        )
        self._reconnect = False

    def get_client(self, config=None):
        with self._lock:
            cached = SunSpecApiClient.CLIENT_CACHE.get(self._client_key, None)
            if cached is None or config is not None:
                _LOGGER.debug("Not using cached connection")
                cached = self.modbus_connect(config)
                SunSpecApiClient.CLIENT_CACHE[self._client_key] = cached
            if self._reconnect:
                if self.check_port():
                    cached.connect()
                    self._reconnect = False
            return cached

    def disconnect(self):
        """Forget the scanned device and close its connection if no other uses it."""
        with self._lock:
            client = SunSpecApiClient.CLIENT_CACHE.pop(self._client_key, None)
            if client is not None and all(
                other.client is not client.client
                for other in SunSpecApiClient.CLIENT_CACHE.values()
            ):
                client.disconnect()

    def async_get_client(self, config=None):
        return self._hass.async_add_executor_job(self.get_client, config)

    async def async_get_data(self, model_id) -> SunSpecModelWrapper:
        try:
            _LOGGER.debug("Get data for model %s", model_id)
            return await self.read(model_id)
        except SunSpecModbusClientTimeout as timeout_error:
            _LOGGER.warning("Async get data timeout")
            raise ConnectionTimeoutError() from timeout_error
        except SunSpecModbusClientException as connect_error:
            _LOGGER.warning("Async get data connect_error")
            raise ConnectionError() from connect_error
        except ModbusClientException as err:
            raise ModelRefusedError(err) from err

    async def read(self, model_id) -> SunSpecModelWrapper:
        return await self._hass.async_add_executor_job(self.read_model, model_id)

    async def async_get_device_info(self) -> SunSpecModelWrapper:
        return await self.read(1)

    async def async_get_models(self, config=None) -> list:
        _LOGGER.debug("Fetching models")
        client = await self.async_get_client(config)
        model_ids = sorted(list(filter(lambda m: type(m) is int, client.models.keys())))
        return model_ids

    def reconnect_next(self):
        self._reconnect = True

    def check_port(self) -> bool:
        """Check if port is available"""
        with self._lock:
            sock_timeout = float(3)
            _LOGGER.debug(
                f"Check_Port: opening socket on {self._host}:{self._port} with a {sock_timeout}s timeout."
            )
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(sock_timeout)
            sock_res = sock.connect_ex((self._host, self._port))
            is_open = sock_res == 0  # True if open, False if not
            if is_open:
                sock.shutdown(socket.SHUT_RDWR)
                _LOGGER.debug(
                    f"Check_Port (SUCCESS): port open on {self._host}:{self._port}"
                )
            else:
                _LOGGER.debug(
                    f"Check_Port (ERROR): port not available on {self._host}:{self._port} - error: {sock_res}"
                )
            sock.close()
            time.sleep(0.1)
        return is_open

    def modbus_connect(self, config=None):
        use_config = SimpleNamespace(
            **(
                config
                or {"host": self._host, "port": self._port, "unit_id": self._unit_id}
            )
        )
        _LOGGER.debug(
            f"Client connect to IP {use_config.host} port {use_config.port} unit id {use_config.unit_id} using timeout {TIMEOUT}"
        )
        client = modbus_client.SunSpecModbusClientDeviceTCP(
            slave_id=use_config.unit_id,
            ipaddr=use_config.host,
            ipport=use_config.port,
            timeout=TIMEOUT,
        )
        # A device may accept only one connection, so another entry's open
        # connection to it is shared. Changed options get one of their own.
        shared = None
        if config is None:
            shared = next(
                (
                    other.client
                    for other in SunSpecApiClient.CLIENT_CACHE.values()
                    if (other.ipaddr, other.ipport) == (self._host, self._port)
                    and other.is_connected()
                ),
                None,
            )
        if shared is not None:
            client.client = shared
        if shared is not None or self.check_port():
            _LOGGER.debug("Inverter ready for Modbus TCP connection")
            try:
                if shared is None:
                    with self._lock:
                        client.connect()
                if not client.is_connected():
                    raise ConnectionError(
                        f"Failed to connect to {self._host}:{self._port} unit id {self._unit_id}"
                    )
                _LOGGER.debug("Client connected, perform initial scan")
                client.client.slave_id = client.slave_id
                try:
                    client.scan(
                        connect=False,
                        progress=progress,
                        full_model_read=False,
                        delay=0.5,
                    )
                except (ModbusClientException, ModelError) as err:
                    if not client.models:
                        raise
                    _LOGGER.warning(
                        "Scan stopped early, using the models found: %s", err
                    )
                return client
            except ModbusClientError:
                if shared is None:
                    client.disconnect()
                raise ConnectionError(
                    f"Failed to connect to {use_config.host}:{use_config.port} unit id {use_config.unit_id}"
                )
            except Exception:
                # Garbage collection would close it much later, and a device
                # accepts only a few connections.
                if shared is None:
                    client.disconnect()
                raise
        else:
            _LOGGER.debug("Inverter not ready for Modbus TCP connection")
            raise ConnectionError(f"Inverter not active on {self._host}:{self._port}")

    def read_model(self, model_id) -> dict:
        with self._lock:
            client = self.get_client()
            if closed_by_device(client):
                _LOGGER.debug("Device closed the connection, reconnecting")
                self.reconnect_next()
                self.get_client()
            client.client.slave_id = client.slave_id
            models = client.models[model_id]
            for model in models:
                time.sleep(read_delay(client))
                model.read()

        return SunSpecModelWrapper(models)
