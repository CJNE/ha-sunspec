"""Sensor platform for SunSpec."""

import logging
import struct

from homeassistant.components.sensor import RestoreSensor
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor import SensorStateClass
from homeassistant.const import DEGREE
from homeassistant.const import PERCENTAGE
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
from homeassistant.const import UnitOfReactiveEnergy
from homeassistant.const import UnitOfReactivePower
from homeassistant.const import UnitOfSpeed
from homeassistant.const import UnitOfTemperature
from homeassistant.const import UnitOfTime

from .entity import SunSpecEntity
from .entity import async_add_point_entities

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
    "var": [
        UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        ICON_POWER,
        SensorDeviceClass.REACTIVE_POWER,
    ],
    "Var": [
        UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        ICON_POWER,
        SensorDeviceClass.REACTIVE_POWER,
    ],
    "Varh": [UnitOfReactiveEnergy.VOLT_AMPERE_REACTIVE_HOUR, ICON_DEFAULT, None],
    "W": [UnitOfPower.WATT, ICON_POWER, SensorDeviceClass.POWER],
    "W/m2": [UnitOfIrradiance.WATTS_PER_SQUARE_METER, ICON_DEFAULT, None],
    "Wh": [UnitOfEnergy.WATT_HOUR, ICON_ENERGY, SensorDeviceClass.ENERGY],
    "WH": [UnitOfEnergy.WATT_HOUR, ICON_ENERGY, SensorDeviceClass.ENERGY],
    "bps": [UnitOfDataRate.BITS_PER_SECOND, ICON_DEFAULT, None],
    # Angles, such as an inclination, a position or a wind direction.
    "deg": [DEGREE, ICON_DEFAULT, None],
    "Degrees": [DEGREE, ICON_DEFAULT, None],
    "C": [UnitOfTemperature.CELSIUS, ICON_TEMP, SensorDeviceClass.TEMPERATURE],
    "kWh": [UnitOfEnergy.KILO_WATT_HOUR, ICON_ENERGY, SensorDeviceClass.ENERGY],
    "m/s": [UnitOfSpeed.METERS_PER_SECOND, ICON_DEFAULT, None],
    "mSecs": [UnitOfTime.MILLISECONDS, ICON_DEFAULT, None],
    "meters": [UnitOfLength.METERS, ICON_DEFAULT, None],
    "mm": [UnitOfLength.MILLIMETERS, ICON_DEFAULT, None],
    "%": [PERCENTAGE, ICON_DEFAULT, None],
    "Pct": [PERCENTAGE, ICON_DEFAULT, None],
    "Secs": [UnitOfTime.SECONDS, ICON_DEFAULT, None],
    "enum16": [None, ICON_DEFAULT, SensorDeviceClass.ENUM],
    "enum32": [None, ICON_DEFAULT, SensorDeviceClass.ENUM],
    "bitfield16": [None, ICON_DEFAULT, None],
    "bitfield32": [None, ICON_DEFAULT, None],
}

# Points in degrees that give a direction, such as the wind's or a tracker's
# azimuth. Home Assistant averages their statistics around the circle, into 0
# to 360 degrees, which would make a wrong mean of an angle that can be
# negative, such as a latitude, an inclination or an elevation.
DIRECTIONS = {307: {"WndDir"}, 601: {"GlblAzCtl", "AzTrgt", "AzPos", "AzCtl"}}


def float32_decimal(value):
    """Return the shortest decimal that is the same float32 as value."""
    # pysunspec2 widens a float32 to a double, which adds digits the device
    # never sent, such as 49.970001220703125 for 49.97.
    for digits in range(6, 10):
        decimal = float(f"{value:.{digits}g}")
        if struct.pack(">f", decimal) == struct.pack(">f", value):
            return decimal
    return value


async def async_setup_entry(hass, entry, async_add_devices):
    """Setup sensor platform."""
    async_add_point_entities(
        hass,
        entry,
        async_add_devices,
        lambda model_id, model, model_index: model.getKeys(model_index=model_index),
        sensors,
    )


def sensors(coordinator, entry, data):
    """Return the sensor of a point."""
    meta = data["model"].getMeta(data["key"], data["model_index"])
    sunspec_unit = meta.get("units", "")
    ha_meta = HA_META.get(sunspec_unit, [sunspec_unit, None, None])
    device_class = ha_meta[2]
    if device_class == SensorDeviceClass.ENERGY:
        _LOGGER.debug("Adding energy sensor")
        return [SunSpecEnergySensor(coordinator, entry, data)]
    return [SunSpecSensor(coordinator, entry, data)]


class SunSpecSensor(SunSpecEntity, SensorEntity):
    """sunspec Sensor class."""

    def __init__(self, coordinator, config_entry, data):
        super().__init__(coordinator, config_entry, data)
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

        vtype = self._meta["type"]
        if vtype.startswith("enum"):
            self._options = self._meta.get("symbols", None)
            if self._options is None:
                self.use_device_class = None
            else:
                self.use_device_class = SensorDeviceClass.ENUM
                self._options = [item["name"] for item in self._options]

        desc = self._meta.get("label", self.key)
        if self.unit == UnitOfElectricCurrent.AMPERE and "DC" in desc:
            self.use_icon = ICON_DC_AMPS

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

    @property
    def options(self):
        if self.device_class != SensorDeviceClass.ENUM:
            return None
        return self._options

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
        if vtype.startswith(("enum", "bitfield")):
            symbols = self._meta.get("symbols", None)
            if symbols is None:
                return val
            if vtype.startswith("enum"):
                symbol = list(filter(lambda s: s["value"] == val, symbols))
                if len(symbol) == 1:
                    return symbol[0]["name"][:255]
                else:
                    return None
            else:
                # The point reads "not implemented".
                if val is None:
                    return None
                symbols = list(
                    filter(lambda s: (val >> int(s["value"])) & 1 == 1, symbols)
                )
                if len(symbols) > 0:
                    return ",".join(map(lambda s: s["name"], symbols))[:255]
                return ""
        if vtype == "float32" and val is not None:
            return float32_decimal(val)
        return val

    @property
    def native_unit_of_measurement(self):
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
    def state_class(self):
        """Return de device class of the sensor."""
        if self.unit == "" or self.unit is None:
            return None
        if self.device_class == SensorDeviceClass.ENERGY:
            return SensorStateClass.TOTAL_INCREASING
        if self._meta["name"] in DIRECTIONS.get(self.model_id, ()):
            return SensorStateClass.MEASUREMENT_ANGLE
        return SensorStateClass.MEASUREMENT


class SunSpecEnergySensor(SunSpecSensor, RestoreSensor):
    @property
    def native_value(self):
        val = super().native_value
        # For an energy sensor a value of 0 woulld mess up long term stats because of how total_increasing works
        if val == 0:
            _LOGGER.debug(
                "Returning last known value instead of 0 for %s to avoid resetting total_increasing counter",
                self.name,
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
            self.lastKnown = state.native_value
        else:
            _LOGGER.debug(f"{self.name} No previous state was found")
