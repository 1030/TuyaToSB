import sys
import colorsys
import tinytuya
from devices import devices

# Map types to tinytuya classes
device_class = {
    'bulb': tinytuya.BulbDevice,
    'plug': tinytuya.OutletDevice
}


def usage():
    print("Usage:")
    print("  python light_control.py <device> <on|off>")
    print("  python light_control.py <device> hsv <hue> <sat> <val>")
    print("  python light_control.py <device> h <hue>")
    print("  python light_control.py <device> s <sat>")
    print("  python light_control.py <device> v <val>")
    print("  python light_control.py <device> temp <kelvin>")
    print("  python light_control.py <device> bright <0-100>")
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
    0-360\u00b0 and ``s``/``v`` in ``0..1``).
    """

    status = device.status().get('dps', {})
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
                return h, s, v

        r, g, b = (int(colour.get(k, 0)) for k in ("r", "g", "b"))
        return colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)

    if isinstance(colour, str):
        hexstr = colour.lstrip('#').replace(' ', '')
        if len(hexstr) >= 12:
            # "hhhhssssvvvv" (h:0-360, s:0-1000, v:0-1000)
            try:
                h = int(hexstr[0:4], 16) / 360.0
                s = int(hexstr[4:8], 16) / 1000.0
                v = int(hexstr[8:12], 16) / 1000.0
                return h, s, v
            except ValueError:
                pass
        if len(hexstr) >= 6:
            r = int(hexstr[0:2], 16)
            g = int(hexstr[2:4], 16)
            b = int(hexstr[4:6], 16)
            return colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)

    raise ValueError("Unable to determine current colour")


def current_rgb(device):
    """Return the current RGB tuple for *device*."""
    h, s, v = current_hsv(device)
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return int(r * 255), int(g * 255), int(b * 255)


def global_action(func):
    for name in devices:
        d = get_device(name)
        func(d, name)
    sys.exit(0)


def _find_key(status, keys):
    """Return the first entry in *keys* present in *status*."""
    for key in keys:
        if key in status:
            return key
        if isinstance(key, int) and str(key) in status:
            return str(key)
    return None


def _to_percent(val):
    """Return *val* scaled to 0-100 or ``None`` if invalid."""

    try:
        val = int(val)
    except (TypeError, ValueError):
        return None
    if val > 100:
        val = round(val * 100 / 1000)
    return val


def _parse_colour(colour):
    """Return ('#rrggbb', value) from raw colour status."""
    if isinstance(colour, str):
        hexstr = colour.lstrip('#').replace(' ', '')
        if len(hexstr) >= 12:
            try:
                h = int(hexstr[0:4], 16) / 360.0
                s = int(hexstr[4:8], 16) / 1000.0
                v = int(hexstr[8:12], 16) / 1000.0
            except ValueError:
                pass
            else:
                r, g, b = colorsys.hsv_to_rgb(h, s, v)
                return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}", int(v * 100)
        if len(hexstr) >= 6:
            try:
                r = int(hexstr[0:2], 16)
                g = int(hexstr[2:4], 16)
                b = int(hexstr[4:6], 16)
            except ValueError:
                pass
            else:
                return f"#{r:02x}{g:02x}{b:02x}", None
    elif isinstance(colour, dict):
        if all(k in colour for k in ('h', 's', 'v')):
            try:
                h = float(colour.get('h', 0))
                s = float(colour.get('s', 0))
                v = float(colour.get('v', 0))
            except (TypeError, ValueError):
                pass
            else:
                if h > 1:
                    h /= 360.0
                if s > 1:
                    s /= 1000.0
                if v > 1:
                    v /= 1000.0
                r, g, b = colorsys.hsv_to_rgb(h, s, v)
                return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}", int(v * 100)
        if all(k in colour for k in ('r', 'g', 'b')):
            try:
                r = int(colour.get('r', 0))
                g = int(colour.get('g', 0))
                b = int(colour.get('b', 0))
            except (TypeError, ValueError):
                pass
            else:
                return f"#{r:02x}{g:02x}{b:02x}", None
    return None, None

def get_all_states():
    """Return the current state of all configured devices."""

    states = {}
    for name, cfg in devices.items():
        dev = get_device(name)
        dps = dev.status().get('dps', {})
        state = {}
        key = _find_key(dps, ('switch', '1', 20))
        if key is not None:
            state['on'] = bool(dps[key]) if isinstance(dps[key], (bool, int, str)) else dps[key]
        if cfg['type'] == 'bulb':
            mode_key = _find_key(dps, ('mode', 21))
            mode = dps.get(mode_key, 'colour')
            state['mode'] = mode
            if mode in ('colour', 'color'):
                col_key = _find_key(dps, ('colour', 'color', 'colour_data',
                                         'color_data', 24))
                if col_key is not None:
                    hex_colour, val = _parse_colour(dps[col_key])
                    if hex_colour is not None:
                        state['color'] = hex_colour
                    if val is not None:
                        state['value'] = val
                if 'value' not in state:
                    val_key = _find_key(dps, ('bright', 'brightness', 25, 4))
                    if val_key is not None:
                        val = _to_percent(dps[val_key])
                        if val is not None:
                            state['value'] = val
            else:  # assume white mode
                bright_key = _find_key(dps, ('bright', 'brightness', 25, 4))
                if bright_key is not None:
                    val = _to_percent(dps[bright_key])
                    if val is not None:
                        state['brightness'] = val
                temp_key = _find_key(dps, ('temp', 'colourtemp', 'color_temp', 26, 3))
                if temp_key is not None:
                    val = dps[temp_key]
                    if isinstance(val, str):
                        try:
                            val = int(val)
                        except ValueError:
                            val = None
                    if isinstance(val, int):
                        state['temp'] = int(1_000_000 / val) if val else 0
        states[name] = state
    return states


def save_preset(name):
    """Save the current state of all devices to *name*.json."""

    import json

    states = get_all_states()
    filename = f"{name}.json"
    with open(filename, 'w') as fh:
        json.dump(states, fh)
    print(f"Saved preset to {filename}")


def load_preset(name):
    """Load the preset stored in *name*.json and apply it."""

    import json

    filename = f"{name}.json"
    with open(filename) as fh:
        states = json.load(fh)

    for dev_name, state in states.items():
        if dev_name not in devices:
            continue
        cfg = devices[dev_name]
        dev = get_device(dev_name)
        if 'on' in state:
            on_state = state['on']
            if isinstance(on_state, str):
                on_state = on_state.lower() not in ('0', 'false', 'off')
            (dev.turn_on if on_state else dev.turn_off)()
        if cfg['type'] == 'bulb':
            mode = state.get('mode')
            if mode in ('colour', 'color'):
                colour = state.get('color')
                if isinstance(colour, str):
                    hexstr = colour.lstrip('#')
                    if len(hexstr) >= 6:
                        r = int(hexstr[0:2], 16)
                        g = int(hexstr[2:4], 16)
                        b = int(hexstr[4:6], 16)
                        dev.set_colour(r, g, b)
                if 'value' in state and hasattr(dev, 'set_brightness'):
                    try:
                        val = int(state['value'])
                    except (TypeError, ValueError):
                        pass
                    else:
                        dev.set_brightness(val)
            else:
                if 'brightness' in state and hasattr(dev, 'set_brightness'):
                    try:
                        val = int(state['brightness'])
                    except (TypeError, ValueError):
                        pass
                    else:
                        dev.set_brightness(val)
                if 'temp' in state:
                    try:
                        tval = int(state['temp'])
                    except (TypeError, ValueError):
                        pass
                    else:
                        mired = int(1_000_000 / tval) if tval else 0
                        dev.set_colourtemp(mired)


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
