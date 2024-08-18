"""Sensor platform for SunSpec."""

import logging

from homeassistant.components.sensor import RestoreSensor
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor import SensorStateClass
from homeassistant.const import DEGREE
from homeassistant.const import PERCENTAGE
from homeassistant.const import POWER_VOLT_AMPERE_REACTIVE
from homeassistant.const import UnitOfApparentPower
from homeassistant.const import UnitOfDataRate
from homeassistant.const import UnitOfElectricCurrent
from homeassistant.const import UnitOfElectricPotential
from homeassistant.const import UnitOfEnergy
from homeassistant.const import UnitOfFrequency
from homeassistant.const import UnitOfIrradiance
from homeassistant.const import UnitOfLength
from homeassistant.const import UnitOfPower
from homeassistant.const import UnitOfPressure
from homeassistant.const import UnitOfSpeed
from homeassistant.const import UnitOfTemperature
from homeassistant.const import UnitOfTime

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
    "A": [UnitOfElectricCurrent.AMPERE, ICON_AC_AMPS, SensorDeviceClass.CURRENT],
    "HPa": [UnitOfPressure.HPA, ICON_DEFAULT, None],
    "Hz": [UnitOfFrequency.HERTZ, ICON_FREQ, None],
    "Mbps": [UnitOfDataRate.MEGABITS_PER_SECOND, ICON_DEFAULT, None],
    "V": [UnitOfElectricPotential.VOLT, ICON_VOLT, SensorDeviceClass.VOLTAGE],
    "VA": [UnitOfApparentPower.VOLT_AMPERE, ICON_POWER, None],
    "VAr": [POWER_VOLT_AMPERE_REACTIVE, ICON_POWER, None],
    "W": [UnitOfPower.WATT, ICON_POWER, SensorDeviceClass.POWER],
    "W/m2": [UnitOfIrradiance.WATTS_PER_SQUARE_METER, ICON_DEFAULT, None],
    "Wh": [UnitOfEnergy.WATT_HOUR, ICON_ENERGY, SensorDeviceClass.ENERGY],
    "WH": [UnitOfEnergy.WATT_HOUR, ICON_ENERGY, SensorDeviceClass.ENERGY],
    "bps": [UnitOfDataRate.BITS_PER_SECOND, ICON_DEFAULT, None],
    "deg": [DEGREE, ICON_TEMP, SensorDeviceClass.TEMPERATURE],
    "Degrees": [DEGREE, ICON_TEMP, SensorDeviceClass.TEMPERATURE],
    "C": [UnitOfTemperature.CELSIUS, ICON_TEMP, SensorDeviceClass.TEMPERATURE],
    "kWh": [UnitOfEnergy.KILO_WATT_HOUR, ICON_ENERGY, SensorDeviceClass.ENERGY],
    "m/s": [UnitOfSpeed.METERS_PER_SECOND, ICON_DEFAULT, None],
    "mSecs": [UnitOfTime.MILLISECONDS, ICON_DEFAULT, None],
    "meters": [UnitOfLength.METERS, ICON_DEFAULT, None],
    "mm": [UnitOfLength.MILLIMETERS, ICON_DEFAULT, None],
    "%": [PERCENTAGE, ICON_DEFAULT, None],
    "Secs": [UnitOfTime.SECONDS, ICON_DEFAULT, None],
    "enum16": [None, ICON_DEFAULT, SensorDeviceClass.ENUM],
    "bitfield32": [None, ICON_DEFAULT, SensorDeviceClass.ENUM],
}


async def async_setup_entry(hass, entry, async_add_devices):
    """Setup sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    sensors = []
    device_info = await coordinator.api.async_get_device_info()
    prefix = entry.options.get(CONF_PREFIX, entry.data.get(CONF_PREFIX, ""))
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

                meta = model_wrapper.getMeta(key)
                sunspec_unit = meta.get("units", "")
                ha_meta = HA_META.get(sunspec_unit, [sunspec_unit, None, None])
                device_class = ha_meta[2]
                if device_class == SensorDeviceClass.ENERGY:
                    _LOGGER.debug("Adding energy sensor")
                    sensors.append(SunSpecEnergySensor(coordinator, entry, data))
                else:
                    sensors.append(SunSpecSensor(coordinator, entry, data))

    async_add_devices(sensors)


class SunSpecSensor(SunSpecEntity, SensorEntity):
    """sunspec Sensor class."""

    def __init__(self, coordinator, config_entry, data):
        super().__init__(
            coordinator, config_entry, data["device_info"], data["model"].getGroupMeta()
        )
        self.model_id = data["model_id"]
        self.model_index = data["model_index"]
        self.model_wrapper = data["model"]
        self.key = data["key"]
        self._meta = self.model_wrapper.getMeta(self.key)
        self._group_meta = self.model_wrapper.getGroupMeta()
        self._point_meta = self.model_wrapper.getPoint(self.key).pdef
        sunspec_unit = self._meta.get("units", self._meta.get("type", ""))
        ha_meta = HA_META.get(sunspec_unit, [sunspec_unit, ICON_DEFAULT, None])
        self.unit = ha_meta[0]
        self.use_icon = ha_meta[1]
        self.use_device_class = ha_meta[2]
        self._options = []
        # Used if this is an energy sensor and the read value is 0
        # Updated wheneve the value read is not 0
        self.lastKnown = None
        self._assumed_state = False

        self._uniqe_id = get_sunspec_unique_id(
            config_entry.entry_id, self.key, self.model_id, self.model_index
        )

        vtype = self._meta["type"]
        if vtype in ("enum16", "bitfield32"):
            self._options = self._point_meta.get("symbols", None)
            if self._options is None:
                self.use_device_class = None
            else:
                self.use_device_class = SensorDeviceClass.ENUM
                self._options = [item["name"] for item in self._options]
                self._options.append("")

        self._device_id = config_entry.entry_id
        name = self._group_meta.get("name", str(self.model_id))
        if self.model_index > 0:
            name = f"{name} {self.model_index}"
        key_parts = self.key.split(":")
        if len(key_parts) > 1:
            name = f"{name} {key_parts[0]} {key_parts[1]}"

        desc = self._meta.get("label", self.key)
        if self.unit == UnitOfElectricCurrent.AMPERE and "DC" in desc:
            self.use_icon = ICON_DC_AMPS

        if data["prefix"] != "":
            name = f"{data['prefix']} {name}"

        self._name = f"{name.capitalize()} {desc}"
        _LOGGER.debug(
            "Created sensor for %s in model %s using prefix %s: %s uid %s, device class %s unit %s",
            self.key,
            self.model_id,
            data["prefix"],
            self._name,
            self._uniqe_id,
            self.use_device_class,
            self.unit,
        )
        if self.device_class == SensorDeviceClass.ENUM:
            _LOGGER.debug("Valid options for ENUM: %s", self._options)

    # def async_will_remove_from_hass(self):
    #    _LOGGER.debug(f"Will remove sensor {self._uniqe_id}")

    @property
    def options(self):
        if self.device_class != SensorDeviceClass.ENUM:
            return None
        return self._options

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return self._uniqe_id

    @property
    def assumed_state(self):
        return self._assumed_state

    @property
    def native_value(self):
        """Return the state of the sensor."""
        try:
            val = self.coordinator.data[self.model_id].getValue(
                self.key, self.model_index
            )
        except KeyError:
            _LOGGER.warning("Model %s not found", self.model_id)
            return None
        except OverflowError:
            _LOGGER.warning(
                "Math overflow error when retreiving calculated value for %s", self.key
            )
            return None
        vtype = self._meta["type"]
        if vtype in ("enum16", "bitfield32"):
            symbols = self._point_meta.get("symbols", None)
            if symbols is None:
                return val
            if vtype == "enum16":
                symbol = list(filter(lambda s: s["value"] == val, symbols))
                if len(symbol) == 1:
                    return symbol[0]["name"][:255]
                else:
                    return None
            else:
                symbols = list(
                    filter(lambda s: (val >> int(s["value"])) & 1 == 1, symbols)
                )
                if len(symbols) > 0:
                    return ",".join(map(lambda s: s["name"], symbols))[:255]
                return ""
        return val

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement."""
        # if self.unit == "":
        #     _LOGGER.debug(f"UNIT IS NONT FOR {self.name}")
        #    return None
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
    def state_class(self):
        """Return de device class of the sensor."""
        if self.unit == "" or self.unit is None:
            return None
        if self.device_class == SensorDeviceClass.ENERGY:
            return SensorStateClass.TOTAL_INCREASING
        return SensorStateClass.MEASUREMENT

    @property
    def extra_state_attributes(self):
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


class SunSpecEnergySensor(SunSpecSensor, RestoreSensor):
    def __init__(self, coordinator, config_entry, data):
        super().__init__(coordinator, config_entry, data)
        self.last_known_value = None

    @property
    def native_value(self):
        val = super().native_value
        # For an energy sensor a value of 0 woulld mess up long term stats because of how total_increasing works
        if val == 0:
            _LOGGER.debug(
                "Returning last known value instead of 0 for {self.name) to avoid resetting total_increasing counter"
            )
            self._assumed_state = True
            return self.lastKnown
        self.lastKnown = val
        self._assumed_state = False
        return val

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()
        _LOGGER.debug(f"{self.name} Fetch last known state")
        state = await self.async_get_last_sensor_data()
        if state:
            _LOGGER.debug(
                f"{self.name} Got last known value from state: {state.native_value}"
            )
            self.last_known_value = state.native_value
        else:
            _LOGGER.debug(f"{self.name} No previous state was found")
