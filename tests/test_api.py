"""Tests for SunSpec api."""

import errno
import socket
import struct

import pytest
from sunspec2.device import ModelError
from sunspec2.modbus.client import SunSpecModbusClientError
from sunspec2.modbus.modbus import ModbusClientError
from sunspec2.modbus.modbus import ModbusClientException
from sunspec2.modbus.modbus import ModbusClientTimeout

from custom_components.sunspec.api import ConnectionError
from custom_components.sunspec.api import ConnectionTimeoutError
from custom_components.sunspec.api import DraftAwareModel
from custom_components.sunspec.api import NoSunSpecError
from custom_components.sunspec.api import SunSpecApiClient


async def test_api(hass, sunspec_client_mock):
    """Test API calls."""

    # To test the api submodule, we first create an instance of our API client
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    models = await api.async_get_models()
    assert models == [
        1,
        103,
        160,
        304,
        701,
        702,
        703,
        704,
        705,
        706,
        707,
        708,
        709,
        710,
        711,
        712,
    ]

    device_info = await api.async_get_device_info()

    assert device_info.getValue("Mn") == "SunSpecTest"
    assert device_info.getValue("SN") == "sn-123456789"

    model = await api.async_get_data(701)
    assert model.getValue("W") == 9800
    assert model.getMeta("W")["label"] == "Active Power"

    model = await api.async_get_data(705)
    keys = model.getKeys()
    assert len(keys) == 22


async def test_get_client(hass, sunspec_modbus_client_mock):
    SunSpecApiClient.CLIENT_CACHE = {}
    """Test API calls."""

    # To test the api submodule, we first create an instance of our API client
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)
    client = api.get_client()
    client.scan.assert_called_once()

    SunSpecApiClient.CLIENT_CACHE = {}


async def test_modbus_connect(hass, sunspec_modbus_client_mock):
    SunSpecApiClient.CLIENT_CACHE = {}
    """Test API calls."""

    # To test the api submodule, we first create an instance of our API client
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)
    SunSpecApiClient.CLIENT_CACHE = {}
    client = api.get_client()
    client.scan.assert_called_once()

    SunSpecApiClient.CLIENT_CACHE = {}


async def test_modbus_connect_fail(hass, mocker):
    mocker.patch(
        # api_call is from slow.py but imported to main.py
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.connect",
        return_value={},
    )
    mocker.patch(
        # api_call is from slow.py but imported to main.py
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.is_connected",
        return_value=False,
    )
    mocker.patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
    )
    """Test API calls."""

    # To test the api submodule, we first create an instance of our API client
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    with pytest.raises(ConnectionError):
        api.modbus_connect()


@pytest.mark.parametrize(
    ("connect_result", "is_open"), [(0, True), (errno.ECONNREFUSED, False)]
)
async def test_check_port(hass, mocker, connect_result, is_open):
    sock = mocker.patch("custom_components.sunspec.api.socket.socket").return_value
    sock.connect_ex.return_value = connect_result
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    assert api.check_port() is is_open
    sock.settimeout.assert_called_once_with(3)
    assert socket.getdefaulttimeout() is None


@pytest.mark.parametrize(
    "error",
    [
        ModbusClientException("Modbus exception 2"),
        ModelError("Repeating group count not consistent with model length"),
    ],
)
async def test_modbus_connect_partial_scan(hass, mocker, error):
    """Test that a scan ended by an exception or a model it cannot parse keeps the models found."""

    def scan(self, **kwargs):
        self.models[1] = ["common"]
        raise error

    mocker.patch("sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.connect")
    mocker.patch(
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.is_connected",
        return_value=True,
    )
    mocker.patch("sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.scan", scan)
    mocker.patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
    )
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    assert api.modbus_connect().models == {1: ["common"]}


def model(model_id, length, values):
    """Return a model of the given length, zero apart from values by offset."""
    body = [0] * length
    for offset, value in values.items():
        body[offset] = value & 0xFFFF
    return model_id, body


@pytest.mark.parametrize(
    ("battery", "points"),
    [
        # An E3DC S10 serves 801 to 803 as defined in 2015 (#62).
        (
            [
                model(801, 22, {9: 55}),
                model(802, 20, {3: 500}),
                model(803, 32, {1: 3350, 12: -3}),
            ],
            {801: ("SoC", 55), 802: ("CycleCt", 500), 803: ("BMaxCellVol", 3.35)},
        ),
        (
            [model(802, 62, {9: 77}), model(803, 58, {0: 1})],
            {802: ("SoC", 77), 803: ("NStr", 1)},
        ),
    ],
)
async def test_battery_model_definitions(hass, mocker, battery, points):
    """Test that 801 to 803 at their 2015 lengths are read with the 2015 definitions."""
    registers = [0x5375, 0x6E53]
    for model_id, body in [model(1, 66, {}), *battery, model(103, 50, {})]:
        registers += [model_id, len(body), *body]
    registers = dict(enumerate([*registers, 0xFFFF, 0], start=40000))

    def read(self, addr, count, op=None):
        # pysunspec2 passes floats, which its Modbus client packs as integers.
        addr, count = int(addr), int(count)
        return b"".join(registers.get(addr + i, 0).to_bytes(2) for i in range(count))

    mocker.patch("sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.connect")
    mocker.patch(
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.is_connected",
        return_value=True,
    )
    mocker.patch("sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.read", read)
    mocker.patch("sunspec2.modbus.client.time.sleep")
    mocker.patch("custom_components.sunspec.api.time.sleep")
    mocker.patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
    )
    api = SunSpecApiClient(host="battery", port=123, unit_id=1, hass=hass)

    assert await api.async_get_models() == sorted([1, 103, *points])
    for model_id, (point, value) in points.items():
        assert api.read_model(model_id).getValue(point) == value
    api.disconnect()


@pytest.mark.parametrize("closed", [True, False])
async def test_read_model_reconnects_closed_connection(hass, mocker, closed):
    """Test that a connection the device closed is reopened before reading."""
    sock, device_end = socket.socketpair()
    if closed:
        device_end.close()
    client = mocker.Mock(models={1: []})
    client.client.socket = sock
    SunSpecApiClient.CLIENT_CACHE["test:123:1"] = client
    mocker.patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
    )
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    api.read_model(1)

    assert client.connect.called is closed
    sock.close()
    device_end.close()


async def test_entries_share_connection(hass, mocker):
    """Test that entries on one host and port share its connection."""
    sock, device_end = socket.socketpair()
    sent = []

    def connect(self, timeout=None):
        self.socket = sock

    def scan(self, **kwargs):
        sent.append(self.client.slave_id)
        model = mocker.Mock()
        model.read.side_effect = lambda: sent.append(self.client.slave_id)
        self.models[103] = [model]

    connect = mocker.patch(
        "sunspec2.modbus.modbus.ModbusClientTCP.connect",
        autospec=True,
        side_effect=connect,
    )
    mocker.patch("sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.scan", scan)
    mocker.patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
    )
    mocker.patch("custom_components.sunspec.api.time.sleep")
    inverter = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)
    meter = SunSpecApiClient(host="test", port=123, unit_id=2, hass=hass)

    inverter.read_model(103)
    meter.read_model(103)
    inverter.read_model(103)

    assert connect.call_count == 1
    assert sent == [1, 1, 2, 2, 1]
    inverter.disconnect()
    assert sock.fileno() != -1
    meter.disconnect()
    assert sock.fileno() == -1
    device_end.close()


async def test_changed_settings_leave_entry_device(hass, mocker):
    """Test that models read with changed settings leave the entry on its device."""

    def scan(self, **kwargs):
        self.models[self.slave_id * 100 + 3] = [mocker.Mock()]

    mocker.patch("sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.connect")
    mocker.patch(
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.is_connected",
        return_value=True,
    )
    disconnect = mocker.patch(
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.disconnect"
    )
    mocker.patch("sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.scan", scan)
    mocker.patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
    )
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    assert await api.async_get_models() == [103]
    changed = {"host": "test", "port": 123, "unit_id": 2}
    assert await api.async_get_models(changed) == [203]
    assert await api.async_get_models() == [103]
    disconnect.assert_called_once()


@pytest.mark.parametrize("scan_error", [None, ModbusClientTimeout("Response timeout")])
async def test_serial_connection(hass, mocker, scan_error):
    """Test that a serial entry reads over its port and then releases the port."""
    rtu = mocker.patch("sunspec2.modbus.client.SunSpecModbusClientDeviceRTU")
    rtu.return_value.scan.side_effect = scan_error
    check_port = mocker.patch("custom_components.sunspec.SunSpecApiClient.check_port")
    api = SunSpecApiClient(None, None, 1, hass, "/dev/ttyUSB0", 9600, "N")

    if scan_error:
        with pytest.raises(ConnectionError):
            api.get_client()
    else:
        api.get_client()
        api.disconnect()

    rtu.assert_called_once_with(
        slave_id=1,
        name="/dev/ttyUSB0",
        baudrate=9600,
        parity="N",
        timeout=3,
        model_class=DraftAwareModel,
    )
    check_port.assert_not_called()
    rtu.return_value.close.assert_called_once()


async def test_serial_poll_reopens_port(hass, mocker):
    """Test that the poll after a failed one reopens the serial port."""
    rtu = mocker.patch("sunspec2.modbus.client.SunSpecModbusClientDeviceRTU")
    api = SunSpecApiClient(None, None, 1, hass, "/dev/ttyUSB0", 9600, "N")
    api.get_client()

    api.reconnect_next()
    api.get_client()

    rtu.return_value.client.close.assert_called_once()
    rtu.return_value.client.open.assert_called_once()


@pytest.mark.parametrize(
    ("error", "raised"),
    [
        (ModbusClientTimeout("Response timeout"), ConnectionTimeoutError),
        (ModbusClientError("Socket write error"), ConnectionError),
        (
            SunSpecModbusClientError("Error scanning SunSpec base addresses."),
            NoSunSpecError,
        ),
        (struct.error("'H' format requires 0 <= number <= 65535"), struct.error),
    ],
)
async def test_modbus_connect_failed_scan_closes(hass, mocker, error, raised):
    """Test that a failed scan closes its connection."""
    mocker.patch("sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.connect")
    mocker.patch(
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.is_connected",
        return_value=True,
    )
    mocker.patch(
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.scan", side_effect=error
    )
    disconnect = mocker.patch(
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.disconnect"
    )
    mocker.patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
    )
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    with pytest.raises(raised):
        api.modbus_connect()

    disconnect.assert_called_once()


async def test_modbus_connect_exception(hass, mocker):
    mocker.patch(
        # api_call is from slow.py but imported to main.py
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.connect",
        side_effect=ModbusClientError,
    )
    mocker.patch(
        # api_call is from slow.py but imported to main.py
        "sunspec2.modbus.client.SunSpecModbusClientDeviceTCP.is_connected",
        return_value=False,
    )
    mocker.patch(
        "custom_components.sunspec.SunSpecApiClient.check_port", return_value=True
    )
    """Test API calls."""

    # To test the api submodule, we first create an instance of our API client
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    with pytest.raises(ConnectionError):
        api.modbus_connect()


@pytest.mark.parametrize(("manufacturer", "delay"), [("SMA", 1), ("Fronius", 0.6)])
async def test_read_model_delay(hass, mocker, manufacturer, delay):
    """Test that an SMA device gets a second before each model read."""
    sleep = mocker.patch("custom_components.sunspec.api.time.sleep")
    common = mocker.Mock(points={"Mn": mocker.Mock(value=manufacturer)})
    client = mocker.Mock(models={1: [common], 103: [mocker.Mock()]})
    client.client.socket = None
    SunSpecApiClient.CLIENT_CACHE["test:123:1"] = client
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    api.read_model(103)

    sleep.assert_called_once_with(delay)


async def test_read_model_timeout(hass, mocker):
    mocker.patch(
        "custom_components.sunspec.api.SunSpecApiClient.read_model",
        side_effect=ModbusClientTimeout("timed out"),
    )
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    with pytest.raises(ConnectionTimeoutError):
        await api.async_get_data(1)


async def test_read_model_error(hass, mocker):
    mocker.patch(
        "custom_components.sunspec.api.SunSpecApiClient.read_model",
        side_effect=ModbusClientError("Socket write error"),
    )
    api = SunSpecApiClient(host="test", port=123, unit_id=1, hass=hass)

    with pytest.raises(ConnectionError):
        await api.async_get_data(1)
