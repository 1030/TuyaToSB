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
    assert states['Bulb']['value'] == 500


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
    assert data['Bulb']['value'] == 500
    assert data['Plug']['on'] is False

    # prepare for load
    bulb.calls.clear()
    plug.calls.clear()

    light_control.load_preset(preset_name)

    assert 'off' in plug.calls  # plug turned off
    assert 'on' in bulb.calls  # bulb turned on from preset
    assert ('colour', 0, 0, 255) in bulb.calls
    assert ('brightness', 500) in bulb.calls


def test_load_preset_uses_hex_brightness(tmp_path, monkeypatch):
    bulb = DummyBulb({'20': True})
    devices = {'Bulb': {'type': 'bulb'}}

    monkeypatch.setattr(light_control, 'devices', devices)
    monkeypatch.setattr(light_control, 'get_device', lambda n: bulb)

    preset = {
        'Bulb': {
            'on': True,
            'mode': 'colour',
            'color': '016203e803e8',
            'value': 0,
        }
    }
    preset_name = str(tmp_path / 'preset')
    with open(preset_name + '.json', 'w') as fh:
        json.dump(preset, fh)

    light_control.load_preset(preset_name)

    assert ('colour', 255, 0, 25) in bulb.calls
    assert ('brightness', 1000) in bulb.calls


def test_get_all_states_uses_hex_brightness(monkeypatch):
    bulb = DummyBulb({
        '20': True,
        '21': 'colour',
        'colour_data': '016203e803e8',
        '25': '0',
    })
    devices = {'Bulb': {'type': 'bulb'}}

    monkeypatch.setattr(light_control, 'devices', devices)
    monkeypatch.setattr(light_control, 'get_device', lambda n: bulb)

    states = light_control.get_all_states()
    assert states['Bulb']['color'] == '016203e803e8'
    assert states['Bulb']['value'] == 1000


def test_brightness_key_named_value(tmp_path, monkeypatch):
    bulb = DummyBulb({'20': False, '21': 'colour', '24': '#00ff00', 'value': '40'})
    plug = DummyPlug({'1': True})

    devices = {'Bulb': {'type': 'bulb'}, 'Plug': {'type': 'plug'}}

    monkeypatch.setattr(light_control, 'devices', devices)
    monkeypatch.setattr(light_control, 'get_device', lambda n: bulb if n == 'Bulb' else plug)

    preset_name = str(tmp_path / 'preset')

    light_control.save_preset(preset_name)

    with open(preset_name + '.json') as fh:
        data = json.load(fh)

    assert data['Bulb']['value'] == 40

    bulb.calls.clear()
    plug.calls.clear()

    light_control.load_preset(preset_name)

    assert ('brightness', 40) in bulb.calls


def test_load_preset_can_ignore_plugs(tmp_path, monkeypatch):
    bulb = DummyBulb({'20': False, '21': 'colour', '24': '#0000ff', '25': '40'})
    plug = DummyPlug({'1': True})

    devices = {'Bulb': {'type': 'bulb'}, 'Plug': {'type': 'plug'}}

    monkeypatch.setattr(light_control, 'devices', devices)
    monkeypatch.setattr(light_control, 'get_device', lambda n: bulb if n == 'Bulb' else plug)
    monkeypatch.setattr(light_control, 'UPDATE_PLUGS_ON_PRESET_LOAD', False)

    preset = {
        'Bulb': {'on': True, 'mode': 'colour', 'color': '#123456', 'value': 40},
        'Plug': {'on': False},
    }
    preset_name = str(tmp_path / 'preset')
    with open(preset_name + '.json', 'w') as fh:
        json.dump(preset, fh)

    light_control.load_preset(preset_name)

    assert 'on' in bulb.calls
    assert plug.calls == []


def test_brightenby_caps_at_256():
    bulb = DummyBulb({'20': True, '21': 'colour', '25': '200'})

    light_control.adjust_brightness(bulb, 100)

    assert ('brightness', light_control.MAX_BRIGHTNESS) in bulb.calls


def test_dimby_floors_at_0():
    bulb = DummyBulb({'20': True, '21': 'white', 'bright': '100'})

    light_control.adjust_brightness(bulb, -200)

    assert ('brightness', 0) in bulb.calls


def test_dimby_uses_bright_value_v2(monkeypatch):
    bulb = DummyBulb({'20': True, '21': 'white', 'bright_value_v2': '800'})

    light_control.adjust_brightness(bulb, -600)

    assert ('brightness', 200) in bulb.calls
