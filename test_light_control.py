import colorsys
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
