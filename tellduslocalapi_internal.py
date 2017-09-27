#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Communicate with Telldus Local API."""
""" TODO: Add token-renewal """

import logging
from datetime import timedelta

import requests
from requests.compat import urljoin
from requests_oauthlib import OAuth1

__version__ = '0.0.1'

_LOGGER = logging.getLogger(__name__)

TIMEOUT = timedelta(seconds=30)

UNNAMED_DEVICE = 'NO NAME'

# Tellstick methods
# pylint:disable=invalid-name
TURNON = 1
TURNOFF = 2
BELL = 4
TOGGLE = 8
DIM = 16
LEARN = 32
UP = 128
DOWN = 256
STOP = 512
RGBW = 1024
THERMOSTAT = 2048

SUPPORTED_METHODS = (
    TURNON |
    TURNOFF |
    DIM |
    UP |
    DOWN |
    STOP)

METHODS = {
    TURNON: 'turnOn',
    TURNOFF: 'turnOff',
    BELL: 'bell',
    TOGGLE: 'toggle',
    DIM: 'dim',
    LEARN: 'learn',
    UP: 'up',
    DOWN: 'down',
    STOP: 'stop',
    RGBW: 'rgbw',
    THERMOSTAT: 'thermostat'
}

# Sensor types
TEMPERATURE = 'temperature',
HUMIDITY = 'humidity',
RAINRATE = 'rrate',
RAINTOTAL = 'rtot',
WINDDIRECTION = 'wdir',
WINDAVERAGE = 'wavg',
WINDGUST = 'wgust',
UV = 'uv',
WATT = 'watt',
LUMINANCE = 'lum',
DEW_POINT = 'dew',  # ?
BAROMETRIC_PRESSURE = '?',


class Client:
    """Telldus Local API client."""

    def __init__(self,
                 ip_address,
                 token):
        #access_token = self._getAccessToken(ip_address, token)
        access_token = token

        self._session = requests.Session()
        self._session.headers = { "Authorization": "Bearer "+access_token }
        self.token = token

        self._state = {}
        self._api_url = "http://"+ip_address+"/api/"

    def _getAccessToken(self, ip_address, token):
        url = "http://"+ip_address+"/api/token?token="+token
        request = requests.get(url)
        data = request.json()
        print(data)
        _LOGGER.debug(data)
        return data.get('token')

    def _device(self, device_id):
        """Return the raw representaion of a device."""
        return self._state.get(device_id)

    def request(self, url, **params):
        """Send a request to the Tellstick Local API."""
        try:
            url = urljoin(self._api_url, url)
            _LOGGER.debug('Request %s %s', url, params)
            response = self._session.get(url,
                                         params=params,
                                         timeout=TIMEOUT.seconds)
            response.raise_for_status()
            _LOGGER.debug('Response %s %s',
                          response.status_code,
                          response.json())
            response = response.json()
            if 'error' in response:
                raise IOError(response['error'])
            return response
        except (OSError, IOError) as error:
            _LOGGER.warning('Failed request: %s', error)

    def execute(self, method, **params):
        """Make request, check result if successful."""
        response = self.request(method, **params)
        return response and response.get('status') == 'success'

    def request_devices(self):
        """Request list of devices from server."""
        res = self.request('devices/list',
                           supportedMethods=SUPPORTED_METHODS,
                           includeIgnored=0)
        return res.get('device') if res else None

    def request_sensors(self):
        """Request list of sensors from server."""
        res = self.request('sensors/list',
                           includeValues=1,
                           includeScale=1,
                           includeIgnored=0)
        return res.get('sensor') if res else None

    def update(self):
        """Updates all devices and sensors from server."""
        self._state = {}

        def collect(devices):
            """Update local state."""
            self._state.update({device['id']: device
                                for device in devices or {}
                                if device['name']})

        devices = self.request_devices()
        collect(devices)

        sensors = self.request_sensors()
        collect(sensors)

        return (devices is not None and
                sensors is not None)

    def device(self, device_id):
        """Return a device object."""
        return Device(self, device_id)

    @property
    def devices(self):
        """Request representations of all devices."""
        return (self.device(device_id) for device_id in self.device_ids)

    @property
    def device_ids(self):
        """List of known device ids."""
        return self._state.keys()


class Device:
    """Tellduslive device."""

    def __init__(self, client, device_id):
        self._client = client
        self._device_id = device_id

    def __str__(self):
        try:
            return unicode(self).encode('utf-8')
        except NameError:
            return self.__unicode__()

    def __unicode__(self):
        if self.is_sensor:
            items = ", ".join(str(item) for item in self.items)
            return "%s #%s \'%s\' (%s)" % (
                "Sensor",
                self.device_id,
                self.name or UNNAMED_DEVICE,
                items)
        else:
            return u"%s #%s \'%s\' (%s:%s) [%s]" % (
                "Device",
                self.device_id,
                self.name or UNNAMED_DEVICE,
                self._str_methods(self.state),
                self.statevalue,
                self._str_methods(self.methods))

    def __getattr__(self, name):
        if (self.device and
                name in ['name', 'state', 'battery',
                         'lastUpdated', 'methods', 'data']):
            return self.device.get(name)

    @property
    def device(self):
        """Return the raw representation of the device."""
        # pylint: disable=protected-access
        return self._client._device(self.device_id)

    @property
    def device_id(self):
        """Id of device."""
        return self._device_id

    @staticmethod
    def _str_methods(val):
        """String representation of methods or state."""
        res = []
        for method in METHODS:
            if val & method:
                res.append(METHODS[method].upper())
        return "|".join(res)

    def _execute(self, command, **params):
        """Send command to server and update local state."""
        params.update(id=self._device_id)
        # Corresponding API methods
        method = 'device/%s' % METHODS[command]
        if self._client.execute(method, **params):
            self.device['state'] = command
            return True

    @property
    def is_sensor(self):
        """Return true if this is a sensor."""
        return 'data' in self.device

    @property
    def statevalue(self):
        """State value of device."""
        return (self.device['statevalue'] if
                self.device and
                self.device['statevalue'] and
                self.device['statevalue'] != 'unde'
                else 0)

    @property
    def is_on(self):
        """Return true if device is on."""
        return (self.state == TURNON or
                self.state == DIM)

    @property
    def is_down(self):
        """Return true if device is down."""
        return self.state == DOWN

    @property
    def dim_level(self):
        """Return current dim level."""
        try:
            return int(self.statevalue)
        except (TypeError, ValueError):
            return None

    def turn_on(self):
        """Turn device on."""
        return self._execute(TURNON)

    def turn_off(self):
        """Turn device off."""
        return self._execute(TURNOFF)

    def dim(self, level):
        """Dim device."""
        if self._execute(DIM, level=level):
            self.device['statevalue'] = level
            return True

    def up(self):
        """Pull device up."""
        return self._execute(UP)

    def down(self):
        """Pull device down."""
        return self._execute(DOWN)

    def stop(self):
        """Stop device."""
        return self._execute(STOP)

    @property
    def items(self):
        """Return sensor items for sensor."""
        return (SensorItem(item) for item in self.data) if self.data else []

    def item(self, name, scale):
        """Return sensor item."""
        return next((item for item in self.items
                     if (item.name == name and
                         item.scale == scale)), None)

    def value(self, name, scale):
        """Return value of sensor item."""
        return self.item(name, scale).value


class SensorItem:
    # pylint: disable=too-few-public-methods, no-member
    """Reference to a sensor data item."""
    def __init__(self, data):
        vars(self).update(data)

    def __str__(self):
        return '%s=%s' % (self.name, self.value)


def main():
    """Dump configured devices and sensors."""
    from os import path
    from sys import argv
    logging.basicConfig(level=logging.INFO)
    try:
        with open(path.join(path.dirname(argv[0]),
                            '.credentials.conf')) as config:
            credentials = dict(
                x.split(': ')
                for x in config.read().strip().splitlines())
    except (IOError, OSError):
        print('Could not read configuration')
        exit(-1)

    client = Client(**credentials)
    client.update()
    print('Devices\n'
          '-------')
    for device in client.devices:
        print(device)
        for item in device.items:
            print('- %s' % item)


if __name__ == '__main__':
    main()
