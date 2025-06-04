import colorsys
import json
import pytest
import sys
import types

# Stub tinytuya before importing the module under test as it is not
# available in the test environment.
tinytuya = types.ModuleType('tinytuya')
tinytuya.BulbDevice = object
tinytuya.OutletDevice = object
sys.modules['tinytuya'] = tinytuya

import light_control

class DummyDevice:
    def __init__(self, color_hex):
        self._status = {'dps': {'color_data': color_hex}}
        self.colour_set = None

    def status(self):
        return self._status

    def set_colour(self, r, g, b):
        self.colour_set = (r, g, b)


class DummyBulb:
    def __init__(self, status):
        self._status = {'dps': status}
        self.calls = []

    def status(self):
        return self._status

    def turn_on(self):
        self.calls.append('on')

    def turn_off(self):
        self.calls.append('off')

    def set_colour(self, r, g, b):
        self.calls.append(('colour', r, g, b))

    def set_brightness(self, b):
        self.calls.append(('brightness', b))

    def set_colourtemp(self, t):
        self.calls.append(('temp', t))


class DummyPlug:
    def __init__(self, status):
        self._status = {'dps': status}
        self.calls = []

    def status(self):
        return self._status

    def turn_on(self):
        self.calls.append('on')

    def turn_off(self):
        self.calls.append('off')


def test_current_hsv_color_data():
    dev = DummyDevice('#00b401f403e8')
    h, s, v = light_control.current_hsv(dev)
    assert h == pytest.approx(0.5)
    assert s == pytest.approx(0.5)
    assert v == pytest.approx(1)


def test_saturation_update_color_data():
    dev = DummyDevice('#00b401f403e8')
    h, s, v = light_control.current_hsv(dev)
    new_s = 0.75
    r, g, b = colorsys.hsv_to_rgb(h, new_s, v)
    dev.set_colour(int(r * 255), int(g * 255), int(b * 255))
    assert dev.colour_set == (int(r * 255), int(g * 255), int(b * 255))


def test_get_all_states(monkeypatch):
    bulb = DummyBulb({'20': True, '21': 'colour', '24': '#ff0000', '25': '80'})
    plug = DummyPlug({'1': False})

    devices = {
        'Bulb': {'type': 'bulb'},
        'Plug': {'type': 'plug'},
    }

    def get_device(name):
        return bulb if name == 'Bulb' else plug

    monkeypatch.setattr(light_control, 'devices', devices)
    monkeypatch.setattr(light_control, 'get_device', get_device)

    states = light_control.get_all_states()
    assert states == {
        'Bulb': {
            'on': True,
            'mode': 'colour',
            'color': '#ff0000',
            'value': 80
        },
        'Plug': {'on': False},
    }


def test_hex_value_parsing(monkeypatch):
    bulb = DummyBulb({'20': True, '21': 'colour', '24': '#ff0000', '25': '01f4'})
    devices = {'Bulb': {'type': 'bulb'}}

    monkeypatch.setattr(light_control, 'devices', devices)
    monkeypatch.setattr(light_control, 'get_device', lambda n: bulb)

    states = light_control.get_all_states()
    assert states['Bulb']['value'] == 50


def test_save_and_load_preset(tmp_path, monkeypatch):
    bulb = DummyBulb({'20': False, '21': 'colour', '24': '#00ff00', '25': '40'})
    plug = DummyPlug({'1': True})

    devices = {'Bulb': {'type': 'bulb'}, 'Plug': {'type': 'plug'}}

    def get_device(name):
        return bulb if name == 'Bulb' else plug

    monkeypatch.setattr(light_control, 'devices', devices)
    monkeypatch.setattr(light_control, 'get_device', get_device)

    preset_name = str(tmp_path / 'preset')

    monkeypatch.setattr(
        light_control,
        'get_all_states',
        lambda: {
            'Bulb': {
                'on': True,
                'mode': 'colour',
                'color': '#0000ff',
                'value': '01f4'
            },
            'Plug': {'on': False},
        },
    )

    light_control.save_preset(preset_name)

    with open(preset_name + '.json') as fh:
        data = json.load(fh)

    assert data['Bulb']['color'] == '#0000ff'
    assert data['Bulb']['value'] == 50
    assert data['Plug']['on'] is False

    # prepare for load
    bulb.calls.clear()
    plug.calls.clear()

    light_control.load_preset(preset_name)

    assert 'off' in plug.calls  # plug turned off
    assert 'on' in bulb.calls  # bulb turned on from preset
    assert ('colour', 0, 0, 255) in bulb.calls
    assert ('brightness', 50) in bulb.calls
