"""Sensor platform for SunSpec."""
import logging

from homeassistant.const import DATA_RATE_BITS_PER_SECOND
from homeassistant.const import DATA_RATE_MEGABITS_PER_SECOND
from homeassistant.const import DEGREE
from homeassistant.const import DEVICE_CLASS_CURRENT
from homeassistant.const import DEVICE_CLASS_ENERGY
from homeassistant.const import DEVICE_CLASS_POWER
from homeassistant.const import DEVICE_CLASS_TEMPERATURE
from homeassistant.const import DEVICE_CLASS_VOLTAGE
from homeassistant.const import ELECTRIC_CURRENT_AMPERE
from homeassistant.const import POWER_VOLT_AMPERE
from homeassistant.const import ENERGY_KILO_WATT_HOUR
from homeassistant.const import ENERGY_WATT_HOUR
from homeassistant.const import FREQUENCY_HERTZ
from homeassistant.const import IRRADIATION_WATTS_PER_SQUARE_METER
from homeassistant.const import LENGTH_METERS
from homeassistant.const import LENGTH_MILLIMETERS
from homeassistant.const import PERCENTAGE
from homeassistant.const import POWER_WATT
from homeassistant.const import PRESSURE_HPA
from homeassistant.const import SPEED_METERS_PER_SECOND
from homeassistant.const import TEMP_CELSIUS
from homeassistant.const import TIME_MILLISECONDS
from homeassistant.const import TIME_SECONDS
from homeassistant.const import VOLT

from . import get_sunspec_unique_id
from .const import CONF_PREFIX
from .const import DOMAIN
from .entity import SunSpecEntity

_LOGGER: logging.Logger = logging.getLogger(__package__)

ICON_DEFAULT = "mdi:information-outline"
ICON_AC_AMPS = "mdi:current-ac"
ICON_DC_AMPS = "mdi:current-dc"
ICON_VOLT = "mdi:lightning-bolt"
ICON_POWER = "mdi:solar-power"
ICON_FREQ = "mdi:sine-wave"
ICON_ENERGY = "mdi:solar-panel"
ICON_TEMP = "mdi:thermometer"

HA_META = {
    "A": [ELECTRIC_CURRENT_AMPERE, ICON_AC_AMPS, DEVICE_CLASS_CURRENT],
    "HPa": [PRESSURE_HPA, ICON_DEFAULT, DEVICE_CLASS_TEMPERATURE],
    "Hz": [FREQUENCY_HERTZ, ICON_FREQ, None],
    "Mbps": [DATA_RATE_MEGABITS_PER_SECOND, ICON_DEFAULT, None],
    "V": [VOLT, ICON_VOLT, DEVICE_CLASS_VOLTAGE],
    "VA": [POWER_VOLT_AMPERE, ICON_POWER, DEVICE_CLASS_POWER],
    "W": [POWER_WATT, ICON_POWER, DEVICE_CLASS_POWER],
    "W/m2": [IRRADIATION_WATTS_PER_SQUARE_METER, ICON_DEFAULT, None],
    "Wh": [ENERGY_WATT_HOUR, ICON_ENERGY, DEVICE_CLASS_ENERGY],
    "WH": [ENERGY_WATT_HOUR, ICON_ENERGY, DEVICE_CLASS_ENERGY],
    "bps": [DATA_RATE_BITS_PER_SECOND, ICON_DEFAULT, None],
    "deg": [DEGREE, ICON_TEMP, DEVICE_CLASS_TEMPERATURE],
    "Degrees": [DEGREE, ICON_TEMP, DEVICE_CLASS_TEMPERATURE],
    "C": [TEMP_CELSIUS, ICON_TEMP, DEVICE_CLASS_TEMPERATURE],
    "kWh": [ENERGY_KILO_WATT_HOUR, ICON_ENERGY, DEVICE_CLASS_ENERGY],
    "m/s": [SPEED_METERS_PER_SECOND, ICON_DEFAULT, None],
    "mSecs": [TIME_MILLISECONDS, ICON_DEFAULT, None],
    "meters": [LENGTH_METERS, ICON_DEFAULT, None],
    "mm": [LENGTH_MILLIMETERS, ICON_DEFAULT, None],
    "%": [PERCENTAGE, ICON_DEFAULT, None],
    "Secs": [TIME_SECONDS, ICON_DEFAULT, None],
}


async def async_setup_entry(hass, entry, async_add_devices):
    """Setup sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    sensors = []
    device_info = await coordinator.api.async_get_device_info()
    prefix = entry.data.get(CONF_PREFIX, "")
    for model_id in coordinator.data.keys():
        model_wrapper = coordinator.data[model_id]
        for key in model_wrapper.getKeys():
            for model_index in range(model_wrapper.num_models):
                data = {
                    "device_info": device_info,
                    "key": key,
                    "model_id": model_id,
                    "model_index": model_index,
                    "model": model_wrapper,
                    "prefix": prefix,
                }
                sensors.append(SunSpecSensor(coordinator, entry, data))
    async_add_devices(sensors)


class SunSpecSensor(SunSpecEntity):
    """sunspec Sensor class."""

    def __init__(self, coordinator, config_entry, data):
        super().__init__(coordinator, config_entry, data["device_info"])
        self.model_id = data["model_id"]
        self.model_index = data["model_index"]
        self.model_wrapper = data["model"]
        self.key = data["key"]
        self._meta = self.model_wrapper.getMeta(self.key)
        self._group_meta = self.model_wrapper.getGroupMeta()
        sunspec_unit = self._meta.get("units", "")
        ha_meta = HA_META.get(sunspec_unit, [sunspec_unit, ICON_DEFAULT, None])
        self.unit = ha_meta[0]
        self.use_icon = ha_meta[1]
        self.use_device_class = ha_meta[2]

        self._uniqe_id = get_sunspec_unique_id(
            config_entry.entry_id, self.key, self.model_id, self.model_index
        )

        self._device_id = config_entry.entry_id
        name = self._group_meta.get("name", str(self.model_id))
        if self.model_index > 0:
            name = f"{name} {self.model_index}"
        key_parts = self.key.split(":")
        if len(key_parts) > 1:
            name = f"{name} {key_parts[0]} {key_parts[1]}"

        desc = self._meta.get("desc", self._meta.get("label", self.key))
        if self.unit == ELECTRIC_CURRENT_AMPERE and "DC" in desc:
            self.use_icon = ICON_DC_AMPS

        if data["prefix"] != "":
            name = f"{data['prefix']} {name}"

        self._name = f"{name.capitalize()} {desc}"
        _LOGGER.debug(
            "Createed sensor for %s in model %s using prefix %s: %s uid %s",
            self.key,
            self.model_id,
            data["prefix"],
            self._name,
            self._uniqe_id,
        )

    # def async_will_remove_from_hass(self):
    #    _LOGGER.debug(f"Will remove sensor {self._uniqe_id}")

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return self._uniqe_id

    @property
    def state(self):
        """Return the state of the sensor."""
        val = self.coordinator.data[self.model_id].getValue(self.key, self.model_index)
        vtype = self._meta["type"]
        if vtype in ("enum16", "bitfield32"):
            symbols = self._meta.get("symbols", None)
            if symbols is None:
                return val
            if vtype == "enum16":
                symbol = list(filter(lambda s: s["value"] == val, symbols))
                if len(symbol) == 1:
                    return symbol[0]["name"]
            else:
                symbols = list(
                    filter(lambda s: (val >> int(s["value"])) & 1 == 1, symbols)
                )
                if len(symbols) > 0:
                    return ",".join(map(lambda s: s["name"], symbols))
                return ""
        return val

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self.unit

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return self.use_icon

    @property
    def device_class(self):
        """Return de device class of the sensor."""
        return self.use_device_class

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        attrs = {
            "integration": DOMAIN,
            "sunspec_key": self.key,
        }
        label = self._meta.get("label", None)
        if label is not None:
            attrs["label"] = label

        vtype = self._meta["type"]
        if vtype in ("enum16", "bitfield32"):
            attrs["raw"] = self.coordinator.data[self.model_id].getValue(
                self.key, self.model_index
            )
        return attrs
