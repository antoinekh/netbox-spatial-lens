"""
Every colour this plugin assigns meaning to.

One source, because the same idea was being spelled out in four places: a cable kind's colour
lived in `cabling.py`, again in the allocation bars, again in the trace panel's hop borders,
and again in the map's polylines. Changing one of them changed the drawing and left the legend
saying something else.

Only *semantic* colour belongs here: the colours that stand for something, where the drawing
and the legend must agree. Chrome that follows the NetBox theme, such as borders and muted
text, uses NetBox's own Bootstrap variables with a fallback and is none of this module's
business.

The palette reaches CSS as custom properties, emitted by `inc/palette.html`, so a rule that
needs one writes `var(--lens-kind-power)` rather than repeating the value.
"""

from collections.abc import Iterable

__all__ = (
    'CATEGORICAL',
    'COMPLETION',
    'COOLING',
    'HIGHLIGHT',
    'HIGHLIGHT_DARK',
    'KIND',
    'LABEL',
    'LABEL_DARK',
    'LABEL_HALO',
    'LABEL_HALO_DARK',
    'NODE',
    'NO_DATA',
    'NO_ROLE',
    'REDUNDANCY',
    'RESERVED_COLOURS',
    'STATUS_COLOURS',
    'UTILISATION',
    'categorical_colour',
    'categorical_series',
    'completion_colour',
    'css_variables',
    'distinct_colours',
    'utilisation_colour',
)

# A cable, a port tick, a trace hop: all coloured by what kind of link it is.
KIND = {
    'interface': '#3f7fbf',
    'power': '#e08a3c',
    'console': '#7b5cc4',
    'passthrough': '#4c9f70',
    'circuit': '#c9483f',
    'other': '#8a8f98',
}

# How full something is, shared by the power and space colourings and by the allocation bars,
# so "nearly full" looks the same wherever it is said.
UTILISATION = (
    (50, '#4c9f70', 'Under 50%'),
    (75, '#d9b23f', '50 to 74%'),
    (90, '#e08a3c', '75 to 89%'),
    (None, '#c9483f', '90% and over'),
)

# What a rack can be cooled by.
COOLING = {
    'air-only': ('#4c9f70', 'Air only'),
    'hybrid': ('#3f7fbf', 'Hybrid'),
    'liquid-only': ('#7b5cc4', 'Liquid only'),
}

# For values that carry no colour of their own, such as a tenant. Picked by a stable hash of
# the name so the same tenant is the same colour on every rack and after every restart.
#
# No grey among them, deliberately. Grey is reserved for "nobody recorded this", and a ring
# holding one hands a named band the reserved colour: a legend then shows two swatches a reader
# cannot tell apart, one of which is the one colour that has to keep its meaning.
CATEGORICAL = (
    '#3f7fbf',
    '#4c9f70',
    '#e08a3c',
    '#7b5cc4',
    '#c9483f',
    '#3fb0bf',
    '#d9b23f',
    '#c2559c',
)

# Turns of the ring, used once it is exhausted. The base hues first, then darker and lighter
# takes on them, which keeps a large legend recognisably one family rather than a scatter.
_RING_FACTORS = (1.0, 0.62, 1.5, 0.8, 1.25, 0.45)

# How much of a thing is wired up.
#
# A ramp rather than the three states this started as, because "partly cabled" covered
# everything from one port of forty-eight to forty-seven of them, and those are not the same
# rack to walk into.
#
# It runs the opposite way to UTILISATION on purpose. There, full is the problem and red means
# "nearly out of room"; here, full is the goal and red means "nothing is plugged in". Reusing
# the utilisation ramp would have made a finished rack look like a failing one.
#
# Nought and complete are their own bands rather than the ends of a gradient: "nothing is
# cabled" and "one port is left" are the two answers anybody acts on, and a ramp that shades
# smoothly through them hides both.
COMPLETION = (
    (0, '#c9483f', 'Nothing cabled'),
    (25, '#e06a3c', 'Under 25%'),
    (50, '#e08a3c', '25 to 49%'),
    (75, '#d9b23f', '50 to 74%'),
    (100, '#8fb45c', '75 to 99%'),
    (None, '#4c9f70', 'Fully cabled'),
)

# The world map's two kinds of point.
# How many power feeds a device reaches: the key, the colour and the legend label. Worst last,
# because the worst device of a rack decides the colour of the rack.
REDUNDANCY = (
    ('redundant', '#4c9f70', 'Two or more feeds'),
    ('untraced', '#d9b23f', 'No feed traced'),
    ('single', '#c9483f', 'One feed'),
)

NODE = {
    'site': '#3f7fbf',
    'provider': '#7b5cc4',
}

# NetBox names its status colours; these are the Bootstrap values behind those names, so a
# device or a site reads the same colour here as on its own page.
STATUS_COLOURS = {
    'green': '#4c9f70',
    'red': '#c9483f',
    'blue': '#3f7fbf',
    'cyan': '#3fb0bf',
    'orange': '#e08a3c',
    'yellow': '#d9b23f',
    'purple': '#7b5cc4',
    'gray': '#8a8f98',
    'grey': '#8a8f98',
}

# A name on the map. The symbol layer draws it over whatever the basemap put there, so it needs
# a halo as much as a colour: a dark name on a dark forest is unreadable without one. The dark
# theme turns both round, because its basemap is dark.
LABEL = '#212529'
LABEL_HALO = '#ffffff'
LABEL_DARK = '#e5e7eb'
LABEL_HALO_DARK = '#111827'

# What the map lights up when a site or a circuit is selected. The same blue as the page's own
# accent in each theme, see `--lens-accent` in lens.css.
HIGHLIGHT = '#0d6efd'
HIGHLIGHT_DARK = '#6ea8fe'

# Grey, for something the plugin has nothing to say about. Deliberately not green: an empty
# field across a whole room must read as "unknown", never as "fine".
NO_DATA = '#b8bcc4'

# A device whose role carries no colour. Distinct from NO_DATA, which means unmeasured.
NO_ROLE = '#6c757d'


def utilisation_colour(percent: float) -> str:
    """
    The band a percentage falls in.
    """
    for threshold, colour, _ in UTILISATION:
        if threshold is None or percent < threshold:
            return colour
    return UTILISATION[-1][1]


def completion_colour(percent: float) -> str:
    """
    The band a completeness percentage falls in.

    Nought and one hundred are exact: a rack with a single port cabled is not "nothing
    cabled", and one with a single port left is not finished. Only the middle is banded.
    """
    if percent <= 0:
        return COMPLETION[0][1]
    if percent >= 100:
        return COMPLETION[-1][1]
    for threshold, colour, _ in COMPLETION[1:-1]:
        if percent < threshold:
            return colour
    return COMPLETION[-2][1]


def _shade(colour: str, factor: float) -> str:
    """
    A lighter or darker turn of one colour.

    Above 1 the colour moves toward white by that fraction of the headroom it has left, so a
    pale yellow does not wash out while a deep blue barely moves. Below 1 it is scaled toward
    black, which darkens every channel by the same proportion and keeps the hue.
    """
    red, green, blue = (int(colour[index : index + 2], 16) for index in (1, 3, 5))
    if factor >= 1:
        mix = factor - 1
        channels = (round(c + (255 - c) * mix) for c in (red, green, blue))
    else:
        channels = (round(c * factor) for c in (red, green, blue))
    return '#{:02x}{:02x}{:02x}'.format(*(max(0, min(255, c)) for c in channels))


def categorical_series(count: int) -> list[str]:
    """
    `count` colours, all different from each other and none of them the no-data grey.

    The ring holds eight, which is fewer than the regions or the tenants a real estate has. Past
    the eighth name the old answer was a colour already spoken for, which put two regions behind
    one swatch on a legend whose whole job is to tell them apart.

    So the ring is walked again at a different lightness each time. Six turns give forty-eight,
    past which a colour legend has stopped being readable by any scheme and the caller gets what
    there is.
    """
    series: list[str] = []
    for factor in _RING_FACTORS:
        for colour in CATEGORICAL:
            shade = colour if factor == 1.0 else _shade(colour, factor)
            if shade != NO_DATA and shade not in series:
                series.append(shade)
            if len(series) == count:
                return series
    return series


def categorical_colour(name: str) -> str:
    """
    A stable colour for a value that has none of its own.

    `hash()` is randomised per process in Python, so using it here would give a tenant one
    colour today and another after a restart, and two colours at once across workers. A CRC is
    not a good hash but it is a fixed one, which is the property that matters.
    """
    from zlib import crc32

    return CATEGORICAL[crc32(name.encode()) % len(CATEGORICAL)]


# The two colours every colouring must leave free: the grey for "not recorded", and the purple
# the world map gives a provider network, which is a point on the map but not a site.
RESERVED_COLOURS = (NO_DATA, NODE['provider'])


def distinct_colours(names: Iterable[str], reserved: Iterable[str] = RESERVED_COLOURS) -> dict[str, str]:
    """
    One colour per name, and never the same colour twice.

    `categorical_colour` derives a colour from the name, which is what keeps a group the same
    colour after a restart and across workers. It cannot promise distinctness: there are eight
    colours, so two names can hash onto one, and that is a legend saying two different things
    with one swatch.

    So the hash is the first choice and the next free slot is the fallback. A name keeps its
    hashed colour whenever nothing else has taken it, which is the usual case, and the names
    are walked in order so that which one gives way does not change between renders.

    The `reserved` colours are taken before any name is served. By default they are the no-data
    grey and the provider purple, which are both bands on the world map; a drawing with no
    provider networks on it reserves only the grey.
    """
    names = sorted(set(names))
    reserved = set(reserved)
    # One free colour per name before any is handed out, plus the reserved ones, so the
    # eleventh region is as distinguishable as the first.
    series = categorical_series(len(names) + len(reserved))
    taken = set(reserved)
    colours: dict[str, str] = {}
    for name in names:
        wanted = categorical_colour(name)
        if wanted in taken:
            wanted = next((c for c in series if c not in taken), wanted)
        colours[name] = wanted
        taken.add(wanted)
    return colours


def css_variables() -> list[str]:
    """
    The palette as CSS custom property declarations.

    Emitted into the page rather than written into the stylesheet, so the stylesheet cannot
    drift from the Python that colours the same things server-side.
    """
    lines = [f'--lens-kind-{name}: {value};' for name, value in KIND.items()]
    lines += [f'--lens-util-{index}: {colour};' for index, (_, colour, _) in enumerate(UTILISATION)]
    lines += [f'--lens-cooling-{name.replace("-", "")}: {colour};' for name, (colour, _) in COOLING.items()]
    lines += [f'--lens-node-{name}: {value};' for name, value in NODE.items()]
    lines += [f'--lens-completion-{index}: {colour};' for index, (_, colour, _) in enumerate(COMPLETION)]
    lines += [f'--lens-no-data: {NO_DATA};', f'--lens-no-role: {NO_ROLE};']
    return lines
