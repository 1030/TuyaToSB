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


if __name__ == '__main__':
    if len(sys.argv) < 2:
        usage()

    cmd = sys.argv[1].lower()

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
