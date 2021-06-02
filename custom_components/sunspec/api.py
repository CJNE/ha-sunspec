"""Sample API Client."""
import logging
import time

import sunspec2.modbus.client as modbus_client
from homeassistant.core import HomeAssistant

TIMEOUT = 5


_LOGGER: logging.Logger = logging.getLogger(__package__)


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
        if point.cvalue is None:
            return point.value
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


class SunSpecApiClient:
    CLIENT_CACHE = {}

    def __init__(self, host: str, port: int, hass: HomeAssistant) -> None:
        """Sunspec modbus client."""

        _LOGGER.debug("New SunspecApi Client")
        self._host = host
        self._port = port
        self._hass = hass
        self._client_key = f"{host}:{port}"

    def get_client(self):
        cached = SunSpecApiClient.CLIENT_CACHE.get(self._client_key, None)
        if cached is None:
            cached = self.modbus_connect()
            SunSpecApiClient.CLIENT_CACHE[self._client_key] = cached
        return cached

    def async_get_client(self):
        return self._hass.async_add_executor_job(self.get_client)

    async def async_get_data(self, model_id) -> SunSpecModelWrapper:
        return await self.read(model_id)

    async def read(self, model_id) -> SunSpecModelWrapper:
        return await self._hass.async_add_executor_job(self.read_model, model_id)

    async def async_get_device_info(self) -> SunSpecModelWrapper:
        return await self.read(1)

    async def async_get_models(self) -> list:
        client = await self.async_get_client()
        model_ids = sorted(list(filter(lambda m: type(m) is int, client.models.keys())))
        return model_ids

    def close(self):
        client = self.get_client()
        client.close()

    def reconnect(self):
        _LOGGER.debug("Client reconnecting")
        client = self.get_client()
        client.connect()

    def modbus_connect(self):
        _LOGGER.debug("Client connect")
        client = modbus_client.SunSpecModbusClientDeviceTCP(
            slave_id=1, ipaddr=self._host, ipport=self._port, timeout=TIMEOUT
        )
        client.scan()
        return client

    def read_model(self, model_id) -> dict:
        client = self.get_client()
        models = client.models[model_id]
        for model in models:
            model.read()
            time.sleep(0.6)

        return SunSpecModelWrapper(models)
