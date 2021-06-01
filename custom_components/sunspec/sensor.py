"""Sensor platform for SunSpec."""
from .const import DEFAULT_NAME
from .const import DOMAIN
from .const import ICON
from .const import SENSOR
from .const import STATE_NAMES
from .entity import SunSpecEntity
from homeassistant.const import (
    ELECTRICAL_CURRENT_AMPERE,
    ELECTRICAL_VOLT_AMPERE,
    IRRADIATION_WATTS_PER_SQUARE_METER,
    DEGREE,
    ENERGY_WATT_HOUR,
    ENERGY_KILO_WATT_HOUR,
    PRESSURE_HPA,
    FREQUENCY_HERTZ,
    DATA_RATE_MEGABITS_PER_SECOND,
    DATA_RATE_BITS_PER_SECOND,
    SPEED_METERS_PER_SECOND,
    TIME_MILLISECONDS,
    TIME_SECONDS,
    LENGTH_METERS,
    LENGTH_MILLIMETERS,
    PERCENTAGE,
    VOLT,
    FREQUENCY_HERTZ,
    POWER_WATT,
    TEMP_CELSIUS,
    TEMP_FAHRENHEIT,
    VOLT,
    )

import logging
_LOGGER: logging.Logger = logging.getLogger(__package__)

HA_UNITS = {
    "A": ELECTRICAL_CURRENT_AMPERE,
    "HPa": PRESSURE_HPA,
    "Hz": FREQUENCY_HERTZ,
    "Mbps": DATA_RATE_MEGABITS_PER_SECOND,
    "V": VOLT,
    "VA": ELECTRICAL_VOLT_AMPERE,
    "W": POWER_WATT,
    "W/m2": IRRADIATION_WATTS_PER_SQUARE_METER,
    "Wh": ENERGY_WATT_HOUR,
    "WH": ENERGY_WATT_HOUR,
    "bps": DATA_RATE_BITS_PER_SECOND,
    "deg": DEGREE,
    "Degrees": DEGREE,
    "C": TEMP_CELSIUS,
    "kWh": ENERGY_KILO_WATT_HOUR,
    "m/s": SPEED_METERS_PER_SECOND,
    "mSecs": TIME_MILLISECONDS,
    "meters": LENGTH_METERS,
    "mm": LENGTH_MILLIMETERS,
    "%": PERCENTAGE,
    "Secs": TIME_SECONDS,
}

ICON_DEFAULT = 'mdi:solar-panel'
ICON_AMPS = 'mdi:solar-panel'
ICON_VOLT = 'mdi:solar-panel'
ICON_POWER = 'mdi:solar-panel'
ICON_FREQ = 'mdi:solar-panel'
ICON_ENERGY = 'mdi:solar-panel'
ICON_TEMP = 'mdi:temperature'


async def async_setup_entry(hass, entry, async_add_devices):
    """Setup sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    sensors = []
    device_info = await coordinator.api.async_get_device_info()
    for model_id in coordinator.data.keys():
        model_wrapper = coordinator.data[model_id]
        for key in model_wrapper.getKeys():
            _LOGGER.debug(f"Create sensor for {key} in model {model_id}")
            for model_index in range(model_wrapper.num_models):
                data = {
                        'device_info': device_info, 'key': key, 'model_id': model_id,
                        'model_index': model_index, 'model': model_wrapper
                }
                sensors.append(SunSpecSensor(coordinator, entry, data))
    async_add_devices(sensors)

class SunSpecSensor(SunSpecEntity):
    """sunspec Sensor class."""
    def __init__(self, coordinator, config_entry, data):
        super().__init__(coordinator, config_entry)
        self.use_icon = ICON_DEFAULT
        self.model_id = data['model_id']
        self.model_index = data['model_index']
        self.model_wrapper = data['model']
        self.key = data['key']
        self._meta = self.model_wrapper.getMeta(self.key)
        self._group_meta = self.model_wrapper.getGroupMeta()
        self.unit = HA_UNITS.get(self._meta['units'], self._meta['units'])
        self._uniqe_id = f"{config_entry.entry_id}_{self.key}-{self.model_id}-{self.model_index}"
        _LOGGER.debug(f"Init sensor {self._uniqe_id}")
        self._device_id = config_entry.entry_id
        name = self._group_meta.get('name', str(self.model_id))
        if(self.model_index > 0):
            name = f"{name} {self.model_index}"
        key_parts = self.key.split(":")
        if(len(key_parts) > 1):
            name = f"{name} {key_parts[0]} {key_parts[1]}"

        self._name = f"{name.capitalize()} {self._meta.get('desc', self._meta.get('label', self.key))}"
        self._device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": data['device_info'].getValue('Md'),
            "model": data['device_info'].getValue('Vr'),
            "manufacturer": data['device_info'].getValue('Mn'),
        }

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return self._uniqe_id

    @property
    def device_info(self):
        return self._device_info

    @property
    def state(self):
        """Return the state of the sensor."""
        val = self.coordinator.data[self.model_id].getValue(self.key, self.model_index)
        vtype = self._meta['type']
        if vtype == 'enum16':
            return self._meta['symbols'][val - 1]
        if vtype in('bitfield32', 'bitfield16'):
            return self._meta['symbols'][val]
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
        return "sunspec__custom_device_class"

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        attrs = {
            "integration": DOMAIN,
            "sunspec_key": self.key,
        }
        label = self._meta.get('label', None)
        if label is not None:
            attrs['label'] = label
        return attrs
