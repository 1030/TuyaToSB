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
    print("  python light_control.py all_on | all_off")
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


def current_rgb(device):
    """Return the current RGB tuple for *device*.

    This tries to parse colour information from the device status in a
    format compatible with :func:`set_colour`. Only the first three bytes
    of any hex string are used if the exact layout is unknown.
    """
    status = device.status().get('dps', {})
    colour = None
    for key in ("colour", "color", "colour_data", "24", 24):
        if key in status:
            colour = status[key]
            break
    if isinstance(colour, dict):
        r, g, b = (colour.get(k, 0) for k in ("r", "g", "b"))
        return int(r), int(g), int(b)
    if isinstance(colour, str) and len(colour) >= 6:
        hexstr = colour.lstrip('#').replace(' ', '')
        return (
            int(hexstr[0:2], 16),
            int(hexstr[2:4], 16),
            int(hexstr[4:6], 16),
        )
    raise ValueError("Unable to determine current colour")


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
        r, g, b = colorsys.hsv_to_rgb(h/360, s/100, v/100)
        device.set_colour(int(r*255), int(g*255), int(b*255))
        print(f"{name} HSV({h},{s},{v})")

    elif action in ('h', 'hue', 's', 'sat', 'v', 'val'):
        if len(sys.argv) != 4:
            usage()
        new_val = int(sys.argv[3])
        r, g, b = current_rgb(device)
        h, s, v = colorsys.rgb_to_hsv(r/255, g/255, b/255)
        if action in ('h', 'hue'):
            h = new_val / 360
        elif action in ('s', 'sat'):
            s = new_val / 100
        else:
            v = new_val / 100
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        device.set_colour(int(r*255), int(g*255), int(b*255))
        print(f"{name} HSV({int(h*360)},{int(s*100)},{int(v*100)})")

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
