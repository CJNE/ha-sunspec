"""Read SunSpec devices over Modbus with pysunspec2."""

import logging
import select
import socket
import threading
import time
from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from sunspec2.device import ModelError
import sunspec2.modbus.client as modbus_client
from sunspec2.modbus.client import SunSpecModbusClientError
from sunspec2.modbus.modbus import ModbusClientError
from sunspec2.modbus.modbus import ModbusClientException
from sunspec2.modbus.modbus import ModbusClientTimeout

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
    """The device refused a model read or write."""


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

    def isWritablePoint(self, point_name):
        point = self.getPoint(point_name)
        return point.value is not None and point.pdef.get("access") == "RW"

    def getKeys(self, valid=None):
        valid = valid or self.isValidPoint
        keys = list(filter(valid, self._models[0].points.keys()))
        for group_name in self._models[0].groups:
            model_group = self._models[0].groups[group_name]
            if type(model_group) is list:
                for idx, group in enumerate(model_group):
                    key_prefix = f"{group_name}:{idx}"
                    group_keys = map(
                        lambda gp: f"{key_prefix}:{gp}", group.points.keys()
                    )
                    keys.extend(filter(valid, group_keys))
            else:
                key_prefix = f"{group_name}:0"
                group_keys = map(
                    lambda gp: f"{key_prefix}:{gp}", model_group.points.keys()
                )
                keys.extend(filter(valid, group_keys))
        return keys

    def getRange(self, point_name, model_index=0):
        """Return the lowest and highest value to write to a point, and its step."""
        point = self.getPoint(point_name, model_index)
        # Reading the value looks up the scale factor the device reports now.
        point.cvalue
        step = 10 ** (point.sf_value or 0)
        units = (point.pdef.get("units") or "").strip()
        signed = point.pdef["type"].startswith("int")
        if units == "cos()":
            return -1, 1, step
        if units == "Pct" or (units.startswith("%") and "/" not in units):
            return -100 if signed else 0, 100, step
        # The value past the highest, or below the lowest if signed, means
        # "not implemented".
        bits = 16 * point.len
        highest = 2 ** (bits - 1) - 1 if signed else 2**bits - 2
        return (-highest if signed else 0) * step, highest * step, step

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
    # A serial port has no socket.
    sock = getattr(client.client, "socket", None)
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

    def __init__(
        self,
        host: str,
        port: int,
        unit_id: int,
        hass: HomeAssistant,
        device: str | None = None,
        baudrate: int | None = None,
        parity: str | None = None,
    ) -> None:
        """Sunspec modbus client, over TCP or, given a device, a serial port."""

        _LOGGER.debug("New SunspecApi Client")
        self._host = host
        self._port = port
        self._hass = hass
        self._unit_id = unit_id
        self._device = device
        self._baudrate = baudrate
        self._parity = parity
        connection = device or f"{host}:{port}"
        self._client_key = f"{connection}:{unit_id}"
        # Entries on one host and port, or one serial port, share its connection
        # and take turns.
        self._lock = SunSpecApiClient.LOCKS.setdefault(connection, threading.RLock())
        self._reconnect = False
        # A disconnected client stays closed: a poll or a setup step still
        # under way must not connect again.
        self._closed = False
        # The write sent to a model, by its ID and index, and not read back.
        self.unconfirmed = {}

    def get_client(self):
        with self._lock:
            if self._closed:
                raise ConnectionError(f"The connection to {self._client_key} is closed")
            cached = SunSpecApiClient.CLIENT_CACHE.get(self._client_key, None)
            if cached is None:
                _LOGGER.debug("Not using cached connection")
                cached = self.modbus_connect()
                SunSpecApiClient.CLIENT_CACHE[self._client_key] = cached
            if self._reconnect:
                if self._device:
                    # The port may have gone with its USB adapter.
                    cached.client.close()
                    cached.client.open()
                    self._reconnect = False
                elif self.check_port():
                    cached.connect()
                    self._reconnect = False
            return cached

    def disconnect(self):
        """Forget the scanned device and close its connection if no other uses it."""
        with self._lock:
            self._closed = True
            client = SunSpecApiClient.CLIENT_CACHE.pop(self._client_key, None)
            if client is None:
                return
            if all(
                other.client is not client.client
                for other in SunSpecApiClient.CLIENT_CACHE.values()
            ):
                client.disconnect()
            # A serial device leaves its port, which closes with the last one.
            client.close()

    async def async_get_data(self, model_id) -> SunSpecModelWrapper:
        _LOGGER.debug("Get data for model %s", model_id)
        return await self.run(self.read_model, model_id)

    async def async_write(self, model_id, model_index, values) -> None:
        try:
            await self.run(self.write_model, model_id, model_index, values)
        except ModelError as err:
            # The point or its scale factor reads "not implemented" now.
            raise ModelRefusedError(err) from err

    async def run(self, job, *args):
        """Run a Modbus job in the executor and raise the integration's errors."""
        try:
            return await self._hass.async_add_executor_job(job, *args)
        # pysunspec2's TCP client lets a write's socket timeout through as it is.
        except (ModbusClientTimeout, TimeoutError) as err:
            raise ConnectionTimeoutError(err) from err
        except ModbusClientException as err:
            raise ModelRefusedError(err) from err
        except ModbusClientError as err:
            raise ConnectionError(err) from err

    async def read(self, model_id) -> SunSpecModelWrapper:
        return await self._hass.async_add_executor_job(self.read_model, model_id)

    async def async_get_device_info(self) -> SunSpecModelWrapper:
        return await self.read(1)

    def get_models(self, config=None) -> list:
        with self._lock:
            if config is None:
                client = self.get_client()
            else:
                # The entry reloads with changed settings and connects anew, so
                # their scan neither stays open nor takes the entry's place.
                client = self.modbus_connect(config)
                client.disconnect()
                client.close()
        return sorted(list(filter(lambda m: type(m) is int, client.models.keys())))

    async def async_get_models(self, config=None) -> list:
        _LOGGER.debug("Fetching models")
        return await self._hass.async_add_executor_job(self.get_models, config)

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
            **{
                "device": None,
                **(
                    config
                    or {
                        "host": self._host,
                        "port": self._port,
                        "unit_id": self._unit_id,
                        "device": self._device,
                        "baudrate": self._baudrate,
                        "parity": self._parity,
                    }
                ),
            }
        )
        if use_config.device:
            target = use_config.device
            _LOGGER.debug(
                f"Client connect to serial port {target} unit id {use_config.unit_id}"
            )
            try:
                client = modbus_client.SunSpecModbusClientDeviceRTU(
                    slave_id=use_config.unit_id,
                    name=target,
                    baudrate=use_config.baudrate,
                    parity=use_config.parity,
                    timeout=SERIAL_TIMEOUT,
                )
            except ModbusClientError as err:
                raise ConnectionError(f"Failed to open {target}: {err}") from err
        else:
            target = f"{use_config.host}:{use_config.port}"
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
        if config is None and not use_config.device:
            shared = next(
                (
                    other.client
                    for other in SunSpecApiClient.CLIENT_CACHE.values()
                    if (getattr(other, "ipaddr", None), getattr(other, "ipport", None))
                    == (self._host, self._port)
                    and other.is_connected()
                ),
                None,
            )
        if shared is not None:
            client.client = shared
        if shared is not None or use_config.device or self.check_port():
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
            except ModbusClientError as err:
                if shared is None:
                    client.disconnect()
                    client.close()
                if isinstance(err, ModbusClientTimeout):
                    raise ConnectionTimeoutError(
                        f"Timed out reading {target} unit id {use_config.unit_id}"
                    ) from err
                raise ConnectionError(
                    f"Failed to connect to {target} unit id {use_config.unit_id}"
                ) from err
            except Exception as err:
                # Garbage collection would close it much later, and a device
                # accepts only a few connections.
                if shared is None:
                    client.disconnect()
                    client.close()
                # The scan found no SunSpec map at any base address.
                if isinstance(err, SunSpecModbusClientError):
                    raise NoSunSpecError(
                        f"No SunSpec data at {target} unit id {use_config.unit_id}"
                    ) from err
                raise
        else:
            _LOGGER.debug("Inverter not ready for Modbus TCP connection")
            raise ConnectionError(f"Inverter not active on {self._host}:{self._port}")

    def unit_client(self):
        """Return the client, ready to send to this entry's unit."""
        client = self.get_client()
        if closed_by_device(client):
            _LOGGER.debug("Device closed the connection, reconnecting")
            self.reconnect_next()
            self.get_client()
        client.client.slave_id = client.slave_id
        return client

    def read_model(self, model_id) -> dict:
        with self._lock:
            client = self.unit_client()
            models = client.models[model_id]
            for model_index, model in enumerate(models):
                time.sleep(read_delay(client))
                model.read()
                self.unconfirmed.pop((model_id, model_index), None)

        return SunSpecModelWrapper(models)

    def write_model(self, model_id, model_index, values) -> None:
        """Write points of a model and read it back.

        A value can also be a function of the point's value as read first.
        """
        with self._lock:
            client = self.unit_client()
            model = client.models[model_id][model_index]
            point = SunSpecModelWrapper([model]).getPoint
            # The scale factors can change while the device runs.
            time.sleep(read_delay(client))
            model.read()
            self.unconfirmed.pop((model_id, model_index), None)
            before = {key: point(key).value for key in values}
            try:
                for key, value in values.items():
                    if before[key] is None:
                        raise ModelError(f"{key} is not implemented")
                    if callable(value):
                        value = value(before[key])
                    scaled = point(key).sf_required
                    point(key).cvalue = value if scaled else round(value)
                time.sleep(read_delay(client))
                # Until the model is read, nobody knows which of these it took.
                self.unconfirmed[model_id, model_index] = values
                model.write()
            except ModbusClientException:
                # The device may have taken the points before the one it refused.
                time.sleep(read_delay(client))
                model.read()
                self.unconfirmed.pop((model_id, model_index), None)
                raise
            except Exception:
                # The entities show the device's values, not the ones it did not
                # take.
                for key, value in before.items():
                    point(key).set_value(value, dirty=False)
                raise
            time.sleep(read_delay(client))
            model.read()
            self.unconfirmed.pop((model_id, model_index), None)
