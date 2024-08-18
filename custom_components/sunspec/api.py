"""Sample API Client."""

import logging
import socket
import threading
import time
from types import SimpleNamespace

from homeassistant.core import HomeAssistant
import sunspec2.modbus.client as modbus_client
from sunspec2.modbus.client import SunSpecModbusClientException
from sunspec2.modbus.client import SunSpecModbusClientTimeout
from sunspec2.modbus.modbus import ModbusClientError

TIMEOUT = 120


_LOGGER: logging.Logger = logging.getLogger(__package__)


class ConnectionTimeoutError(Exception):
    pass


class ConnectionError(Exception):
    pass


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
            for idx, group in enumerate(self._models[0].groups[group_name]):
                key_prefix = f"{group_name}:{idx}"
                group_keys = map(lambda gp: f"{key_prefix}:{gp}", group.points.keys())
                keys.extend(filter(self.isValidPoint, group_keys))
        return keys

    def getValue(self, point_name, model_index=0):
        point = self.getPoint(point_name, model_index)
        return point.cvalue

    def getMeta(self, point_name):
        return self.getPoint(point_name).pdef

    def getGroupMeta(self):
        return self._models[0].gdef

    def getPoint(self, point_name, model_index=0):
        point_path = point_name.split(":")
        if len(point_path) == 1:
            return self._models[model_index].points[point_name]
        return (
            self._models[model_index]
            .groups[point_path[0]][int(point_path[1])]
            .points[point_path[2]]
        )


# pragma: not covered
def progress(msg):
    _LOGGER.debug(msg)
    return True


class SunSpecApiClient:
    CLIENT_CACHE = {}

    def __init__(
        self, host: str, port: int, slave_id: int, hass: HomeAssistant
    ) -> None:
        """Sunspec modbus client."""

        _LOGGER.debug("New SunspecApi Client")
        self._host = host
        self._port = port
        self._hass = hass
        self._slave_id = slave_id
        self._client_key = f"{host}:{port}:{slave_id}"
        self._lock = threading.Lock()

    def get_client(self, config=None, force=False):
        cached = SunSpecApiClient.CLIENT_CACHE.get(self._client_key, None)
        if force or cached is None or config is not None:
            _LOGGER.debug("Not using cached connection")
            cached = self.modbus_connect(config)
            SunSpecApiClient.CLIENT_CACHE[self._client_key] = cached
        return cached

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

    async def read(self, model_id) -> SunSpecModelWrapper:
        return await self._hass.async_add_executor_job(self.read_model, model_id)

    async def async_get_device_info(self) -> SunSpecModelWrapper:
        return await self.read(1)

    async def async_get_models(self, config=None) -> list:
        _LOGGER.debug("Fetching models")
        client = await self.async_get_client(config)
        model_ids = sorted(list(filter(lambda m: type(m) is int, client.models.keys())))
        return model_ids

    def close(self):
        client = self.get_client()
        client.close()

    def reconnect(self):
        _LOGGER.debug("Client reconnecting")
        self.get_client(force=True)

    def check_port(self) -> bool:
        """Check if port is available"""
        with self._lock:
            sock_timeout = float(3)
            _LOGGER.debug(
                f"Check_Port: opening socket on {self._host}:{self._port} with a {sock_timeout}s timeout."
            )
            socket.setdefaulttimeout(sock_timeout)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
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
        return is_open

    def modbus_connect(self, config=None):
        use_config = SimpleNamespace(
            **(
                config
                or {"host": self._host, "port": self._port, "slave_id": self._slave_id}
            )
        )
        _LOGGER.debug(
            f"Client connect to IP {use_config.host} port {use_config.port} slave id {use_config.slave_id} using timeout {TIMEOUT}"
        )
        client = modbus_client.SunSpecModbusClientDeviceTCP(
            slave_id=use_config.slave_id,
            ipaddr=use_config.host,
            ipport=use_config.port,
            timeout=TIMEOUT,
        )
        if self.check_port():
            _LOGGER.debug("Inverter ready for Modbus TCP connection")
            try:
                with self._lock:
                    client.connect()
                if not client.is_connected():
                    raise ConnectionError(
                        f"Failed to connect to {self._host}:{self._port} slave id {self._slave_id}"
                    )
                _LOGGER.debug("Client connected, perform initial scan")
                client.scan(
                    connect=False, progress=progress, full_model_read=False, delay=0.5
                )
                return client
            except ModbusClientError:
                raise ConnectionError(
                    f"Failed to connect to {use_config.host}:{use_config.port} slave id {use_config.slave_id}"
                )
        else:
            _LOGGER.debug("Inverter not ready for Modbus TCP connection")
            raise ConnectionError(f"Inverter not active on {self._host}:{self._port}")

    def read_model(self, model_id) -> dict:
        client = self.get_client()
        models = client.models[model_id]
        for model in models:
            time.sleep(0.6)
            model.read()

        return SunSpecModelWrapper(models)
