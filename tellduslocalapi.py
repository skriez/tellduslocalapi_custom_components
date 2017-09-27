"""
Support for Telldus Local API.

For more details about this component, please refer to the documentation at
XXXXXXXXXXXXXXXXXX
"""
from datetime import datetime, timedelta
import logging
import sys
sys.path.append('/config/custom_components')

from homeassistant.const import (
    ATTR_BATTERY_LEVEL, DEVICE_DEFAULT_NAME, EVENT_HOMEASSISTANT_START)
from homeassistant.helpers import discovery
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import track_point_in_utc_time
from homeassistant.util.dt import utcnow
import voluptuous as vol

DOMAIN = 'tellduslocalapi'

#REQUIREMENTS = ['tellduslocalapi==0.0.1']

_LOGGER = logging.getLogger(__name__)

CONF_TOKEN = 'token'
CONF_HOST = 'host'
CONF_UPDATE_INTERVAL = 'update_interval'

MIN_UPDATE_INTERVAL = timedelta(milliseconds=500)
DEFAULT_UPDATE_INTERVAL = timedelta(minutes=1)

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_TOKEN): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): (
            vol.All(cv.time_period, vol.Clamp(min=MIN_UPDATE_INTERVAL)))
    }),
}, extra=vol.ALLOW_EXTRA)


ATTR_LAST_UPDATED = 'time_last_updated'


def setup(hass, config):
    """Set up the Telldus Live component."""
    client = TelldusLiveClient(hass, config)

    if not client.validate_session():
        _LOGGER.error(
            "Authentication Error: Please make sure you have configured your "
            "keys that can be acquired from "
            "https://api.telldus.com/keys/index")
        return False

    hass.data[DOMAIN] = client

    hass.bus.listen(EVENT_HOMEASSISTANT_START, client.update)

    return True


class TelldusLiveClient(object):
    """Get the latest data and update the states."""

    def __init__(self, hass, config):
        """Initialize the Tellus data object."""
        from tellduslocalapi_internal import Client

        token = config[DOMAIN].get(CONF_TOKEN)
        host = config[DOMAIN].get(CONF_HOST)

        self.entities = []

        self._hass = hass
        self._config = config

        self._interval = config[DOMAIN].get(CONF_UPDATE_INTERVAL)
        _LOGGER.debug('Update interval %s', self._interval)

        self._client = Client(host, token)

    def validate_session(self):
        """Make a request to see if the session is valid."""
        response = self._client.request_devices()
        return response and (len(response) != 0)

    def update(self, *args):
        """Periodically poll the servers for current state."""
        _LOGGER.debug("Updating")
        try:
            self._sync()
        finally:
            track_point_in_utc_time(
                self._hass, self.update, utcnow() + self._interval)

    def _sync(self):
        """Update local list of devices."""
        if not self._client.update():
            _LOGGER.warning("Failed request")

        def identify_device(device):
            """Find out what type of HA component to create."""
            from tellduslocalapi_internal import (DIM, UP, TURNON)
            if device.methods & DIM:
                return 'light'
            elif device.methods & UP:
                return 'cover'
            elif device.methods & TURNON:
                return 'switch'
            _LOGGER.warning(
                "Unidentified device type (methods: %d)", device.methods)
            return 'switch'

        def discover(device_id, component):
            """Discover the component."""
            discovery.load_platform(
                self._hass, component, DOMAIN, [device_id], self._config)

        known_ids = {entity.device_id for entity in self.entities}
        for device in self._client.devices:
            if device.device_id in known_ids:
                continue
            if device.is_sensor:
                for item in device.items:
                    discover((device.device_id, item.name, item.scale),
                             'sensor')
            else:
                discover(device.device_id,
                         identify_device(device))

        for entity in self.entities:
            entity.changed()

    def device(self, device_id):
        """Return device representation."""
        return self._client.device(device_id)

    def is_available(self, device_id):
        """Return device availability."""
        return device_id in self._client.device_ids


class TelldusLiveEntity(Entity):
    """Base class for all Telldus Live entities."""

    def __init__(self, hass, device_id):
        """Initialize the entity."""
        self._id = device_id
        self._client = hass.data[DOMAIN]
        self._client.entities.append(self)
        self._name = self.device.name
        _LOGGER.debug("Created device %s", self)

    def changed(self):
        """Return the property of the device might have changed."""
        if self.device.name:
            self._name = self.device.name
        self.schedule_update_ha_state()

    @property
    def device_id(self):
        """Return the id of the device."""
        return self._id

    @property
    def device(self):
        """Return the representation of the device."""
        return self._client.device(self.device_id)

    @property
    def _state(self):
        """Return the state of the device."""
        return self.device.state

    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def assumed_state(self):
        """Return true if unable to access real state of entity."""
        return True

    @property
    def name(self):
        """Return name of device."""
        return self._name or DEVICE_DEFAULT_NAME

    @property
    def available(self):
        """Return true if device is not offline."""
        return self._client.is_available(self.device_id)

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        attrs = {}
        if self._battery_level:
            attrs[ATTR_BATTERY_LEVEL] = self._battery_level
        if self._last_updated:
            attrs[ATTR_LAST_UPDATED] = self._last_updated
        return attrs

    @property
    def _battery_level(self):
        """Return the battery level of a device."""
        return round(self.device.battery * 100 / 255) \
            if self.device.battery else None

    @property
    def _last_updated(self):
        """Return the last update of a device."""
        return str(datetime.fromtimestamp(self.device.lastUpdated)) \
            if self.device.lastUpdated else None
