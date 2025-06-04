import sys
import colorsys
import tinytuya
from devices import devices

# Map types to tinytuya classes
device_class = {
    'bulb': tinytuya.BulbDevice,
    'plug': tinytuya.OutletDevice
}

# When ``False``, :func:`load_preset` will ignore plug devices
# (i.e. sockets) so that only bulbs are modified.
UPDATE_PLUGS_ON_PRESET_LOAD = True


def usage():
    print("Usage:")
    print("  python light_control.py <device> <on|off>")
    print("  python light_control.py <device> hsv <hue> <sat> <val>")
    print("  python light_control.py <device> h <hue>")
    print("  python light_control.py <device> s <sat>")
    print("  python light_control.py <device> v <val>")
    print("  python light_control.py <device> temp <kelvin>")
    print("  python light_control.py <device> bright <0-1000>")
    print("  python light_control.py <device> get")
    print("  python light_control.py save_preset <name>")
    print("  python light_control.py load_preset <name>")
    print("  python light_control.py all_on | allon | all_off | alloff")
    sys.exit(1)


def resolve_name(raw):
    raw_lower = raw.lower()
    for name in devices:
        if name.lower() == raw_lower or name.replace('_', ' ').lower() == raw_lower:
            return name
    raise KeyError(f"Unknown device: {raw}")


def get_device(name):
    cfg = devices[name]
    cls = device_class.get(cfg['type'])
    if not cls:
        raise ValueError(f"Unsupported device type: {cfg['type']}")

    dev = cls(cfg['gwid'], cfg['ip'], cfg['key'])
    dev.set_socketPersistent(True)
    dev.set_version(cfg['version'])
    try:
        dev.status()
    except Exception:
        pass
    return dev


def current_hsv(device):
    """Return the current colour of *device* as an HSV tuple.

    The Tuya API may return the colour as either an RGB value or an HSV
    encoded hex string (``hhhhssssvvvv``).  Some firmwares store this in
    ``colour_data`` while others use ``color_data``.  This helper
    normalises these formats and returns floating point values
    compatible with :mod:`colorsys` (i.e. ``h`` in ``0..1`` representing
    0-360° and ``s``/``v`` in ``0..1``).
    """

    status = device.status().get('dps', {})
    print(f"[DEBUG] Device status dps: {status}")
    colour = None
    for key in ("colour", "color", "colour_data", "color_data", "24", 24):
        if key in status:
            colour = status[key]
            break

    if isinstance(colour, dict):
        if all(k in colour for k in ("h", "s", "v")):
            try:
                h = float(colour.get("h", 0))
                s = float(colour.get("s", 0))
                v = float(colour.get("v", 0))
            except (TypeError, ValueError):
                pass
            else:
                if h > 1:
                    h /= 360.0
                if s > 1:
                    s /= 1000.0
                if v > 1:
                    v /= 1000.0
                print(f"[DEBUG] current_hsv HSV dict -> h:{h}, s:{s}, v:{v}")
                return h, s, v

        r, g, b = (int(colour.get(k, 0)) for k in ("r", "g", "b"))
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        print(f"[DEBUG] current_hsv RGB dict {r,g,b} -> h:{h}, s:{s}, v:{v}")
        return h, s, v

    if isinstance(colour, str):
        hexstr = colour.lstrip('#').replace(' ', '')
        if len(hexstr) >= 12:
            # "hhhhssssvvvv" (h:0-360, s:0-1000, v:0-1000)
            try:
                h = int(hexstr[0:4], 16) / 360.0
                s = int(hexstr[4:8], 16) / 1000.0
                v = int(hexstr[8:12], 16) / 1000.0
                print(f"[DEBUG] current_hsv HSV hex {hexstr} -> h:{h}, s:{s}, v:{v}")
                return h, s, v
            except ValueError:
                pass
        if len(hexstr) >= 6:
            r = int(hexstr[0:2], 16)
            g = int(hexstr[2:4], 16)
            b = int(hexstr[4:6], 16)
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            print(f"[DEBUG] current_hsv RGB hex {hexstr} -> h:{h}, s:{s}, v:{v}")
            return h, s, v

    raise ValueError("Unable to determine current colour")


def current_rgb(device):
    """Return the current RGB tuple for *device*."""
    h, s, v = current_hsv(device)
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    rgb = int(r * 255), int(g * 255), int(b * 255)
    print(f"[DEBUG] current_rgb -> {rgb}")
    return rgb


def global_action(func):
    for name in devices:
        d = get_device(name)
        func(d, name)
    sys.exit(0)


def _call_no_wait(func, *args, **kwargs):
    """Call *func* with ``nowait=True`` if supported.

    Some of tinytuya's methods (e.g. ``turn_on``) accept a ``nowait``
    keyword indicating the call should return immediately without waiting
    for a response.  When running unit tests the dummy devices don't
    support this parameter so this helper attempts the call with
    ``nowait=True`` first and falls back to a plain call if a ``TypeError``
    is raised.
    """

    try:
        func(*args, **dict(kwargs, nowait=True))
    except TypeError:
        func(*args, **kwargs)


def _find_key(status, keys):
    """Return the first entry in *keys* present in *status*."""
    for key in keys:
        if key in status:
            return key
        if isinstance(key, int) and str(key) in status:
            return str(key)
    return None


def _coerce_level(value):
    """Return *value* coerced to an integer brightness level if possible."""

    if isinstance(value, str):
        cleaned = value.strip().lower().lstrip('#')
        try:
            num = int(cleaned)
        except ValueError:
            if all(c in '0123456789abcdef' for c in cleaned):
                try:
                    num = int(cleaned, 16)
                except ValueError:
                    return value
            else:
                return value
        value = num

    if isinstance(value, int):
        num = value
        if num > 4095:
            num &= 0xFFF
        return num

    return value


def _parse_colour_str(colour):
    """Return an ``(r, g, b, v)`` tuple from *colour* if possible.

    The return is ``(r, g, b, v)`` where ``r``, ``g`` and ``b`` are integers in
    the range ``0..255`` and ``v`` is an optional brightness value in ``0..1000``
    (or ``None`` if brightness is not encoded in the string).
    """

    if not isinstance(colour, str):
        return None, None, None, None

    hexstr = colour.lstrip('#').replace(' ', '')

    if len(hexstr) >= 12:
        try:
            h = int(hexstr[0:4], 16) / 360.0
            s = int(hexstr[4:8], 16) / 1000.0
            v = int(hexstr[8:12], 16)
            r, g, b = colorsys.hsv_to_rgb(h, s, v / 1000.0)
            result = int(r * 255), int(g * 255), int(b * 255), _coerce_level(v)
            print(f"[DEBUG] _parse_colour_str HSV hex {hexstr} -> {result}")
            return result
        except ValueError:
            pass

    if len(hexstr) >= 6 and all(c in '0123456789abcdefABCDEF' for c in hexstr[:6]):
        try:
            r = int(hexstr[0:2], 16)
            g = int(hexstr[2:4], 16)
            b = int(hexstr[4:6], 16)
            result = (r, g, b, None)
            print(f"[DEBUG] _parse_colour_str RGB hex {hexstr} -> {result}")
            return result
        except ValueError:
            pass

    print(f"[DEBUG] _parse_colour_str failed to parse '{colour}'")
    return None, None, None, None


def get_all_states():
    """Return the current state of all configured devices."""

    states = {}
    for name, cfg in devices.items():
        dev = get_device(name)
        dps = dev.status().get('dps', {})
        state = {}
        key = _find_key(dps, ('switch', '1', 20))
        if key is not None:
            state['on'] = dps[key]
        if cfg['type'] == 'bulb':
            mode_key = _find_key(dps, ('mode', 21))
            mode = dps.get(mode_key, 'colour')
            state['mode'] = mode
            if mode in ('colour', 'color'):
                col_key = _find_key(dps, (
                    'colour', 'color', 'colour_data', 'color_data', 24
                ))
                parsed_val = None
                if col_key is not None:
                    colour_val = dps[col_key]
                    state['color'] = colour_val
                    _, _, _, parsed_val = _parse_colour_str(colour_val)

                val_key = _find_key(dps, ('bright', 'brightness', 'value', 25))
                if val_key is not None:
                    val = _coerce_level(dps[val_key])
                    if val == 0 and parsed_val is not None:
                        val = parsed_val
                    state['value'] = val
                elif parsed_val is not None:
                    state['value'] = parsed_val
            else:  # assume white mode
                bright_key = _find_key(dps, ('bright', 'brightness', 'value', 25))
                if bright_key is not None:
                    state['brightness'] = _coerce_level(dps[bright_key])
                temp_key = _find_key(dps, ('temp', 'colourtemp', 'color_temp',
                                          26))
                if temp_key is not None:
                    state['temp'] = dps[temp_key]
        states[name] = state
    return states


def save_preset(name):
    """Save the current state of all devices to *name*.json."""

    import json

    states = get_all_states()
    print(f"[DEBUG] Preset states gathered: {states}")
    for state in states.values():
        if 'value' in state:
            state['value'] = _coerce_level(state['value'])
        if 'brightness' in state:
            state['brightness'] = _coerce_level(state['brightness'])
    filename = f"{name}.json"
    with open(filename, 'w') as fh:
        json.dump(states, fh)
    print(f"[DEBUG] Saved preset to {filename}")


def load_preset(name):
    """Load the preset stored in *name*.json and apply it."""

    import json

    filename = f"{name}.json"
    with open(filename) as fh:
        states = json.load(fh)
    print(f"[DEBUG] Loaded preset from {filename}: {states}")

    for dev_name, state in states.items():
        print(f"[DEBUG] Applying state for {dev_name}: {state}")
        if dev_name not in devices:
            continue
        cfg = devices[dev_name]
        if cfg['type'] == 'plug' and not UPDATE_PLUGS_ON_PRESET_LOAD:
            continue
        dev = get_device(dev_name)
        if 'on' in state:
            func = dev.turn_on if state['on'] else dev.turn_off
            _call_no_wait(func)
        if cfg['type'] == 'bulb':
            mode = state.get('mode')
            if mode in ('colour', 'color'):
                colour = state.get('color')
                r, g, b, default_val = _parse_colour_str(colour)
                if r is not None:
                    print(f"[DEBUG] Loading colour {r,g,b} on {dev_name}")
                    _call_no_wait(dev.set_colour, r, g, b)
                if hasattr(dev, 'set_brightness'):
                    if 'value' in state:
                        val = _coerce_level(state['value'])
                        if val == 0 and default_val is not None:
                            val = default_val
                    else:
                        val = default_val
                    if val is not None:
                        print(f"[DEBUG] Loading brightness {val} on {dev_name}")
                        _call_no_wait(dev.set_brightness, val)
            else:
                if 'brightness' in state and hasattr(dev, 'set_brightness'):
                    bright = _coerce_level(state['brightness'])
                    print(f"[DEBUG] Loading brightness {bright} on {dev_name}")
                    _call_no_wait(dev.set_brightness, bright)
                if 'temp' in state:
                    print(f"[DEBUG] Loading colour temperature {state['temp']} on {dev_name}")
                    _call_no_wait(dev.set_colourtemp, state['temp'])


if __name__ == '__main__':
    if len(sys.argv) < 2:
        usage()

    cmd = sys.argv[1].lower()

    if cmd == 'save_preset' and len(sys.argv) == 3:
        save_preset(sys.argv[2])
        sys.exit(0)

    if cmd == 'load_preset' and len(sys.argv) == 3:
        load_preset(sys.argv[2])
        sys.exit(0)

    if cmd in ('all_on', 'allon', 'alloff', 'all_off'):
        action = 'turn_on' if 'on' in cmd else 'turn_off'
        global_action(lambda d, n: getattr(d, action)(switch=True, nowait=True) or print(f"{n} {action}"))

    if len(sys.argv) < 3:
        usage()

    raw = sys.argv[1]
    try:
        name = resolve_name(raw)
    except KeyError as e:
        print(e)
        sys.exit(1)

    action = sys.argv[2].lower()
    device = get_device(name)

    if action == 'on':
        device.turn_on()
        print(f"{name} on")

    elif action == 'off':
        device.turn_off()
        print(f"{name} off")

    elif action == 'hsv':
        if len(sys.argv) != 6:
            usage()
        h, s, v = map(int, sys.argv[3:6])
        r, g, b = colorsys.hsv_to_rgb(h / 360, s / 100, v / 100)
        device.set_colour(int(r * 255), int(g * 255), int(b * 255))
        print(f"{name} HSV({h},{s},{v})")

    elif action in ('h', 'hue', 's', 'sat', 'v', 'val'):
        if len(sys.argv) != 4:
            usage()
        new_val = int(sys.argv[3])
        h, s, v = current_hsv(device)
        if action in ('h', 'hue'):
            h = new_val / 360
        elif action in ('s', 'sat'):
            s = new_val / 100
        else:
            v = new_val / 100
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        device.set_colour(int(r * 255), int(g * 255), int(b * 255))
        print(f"{name} HSV({int(h * 360)},{int(s * 100)},{int(v * 100)})")

    elif action == 'temp':
        if len(sys.argv) != 4:
            usage()
        k = int(sys.argv[3])
        m = int(1_000_000 / k)
        try:
            device.set_colourtemp(m)
            print(f"{name} {k}K")
        except Exception as e:
            print(f"Failed to set color temperature on {name}: {e}")
            sys.exit(1)

    elif action in ('bright', 'brightness'):
        if len(sys.argv) != 4 or not hasattr(device, 'set_brightness'):
            usage()
        b = int(sys.argv[3])
        device.set_brightness(b)
        print(f"{name} brightness {b}%")

    elif action == 'get':
        status = device.status().get('dps', {})
        print(name, status)

    else:
        usage()
