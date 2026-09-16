"""
Overlays.

An overlay recolours every rack on a floor by one measure: how close it is to its power
limit, whether it can take liquid cooling, how much U-space is left, what its role is. The
floor is the same picture each time; only the colouring changes.

Registration is the extension point. Four overlays ship built in, and another plugin adds its
own from its `ready()` with `register_overlay`, exactly as a pre-merge check is registered in
netbox-change-control. A temperature overlay fed from a monitoring system, a tenancy overlay,
a weight overlay: none of them needs a change in this file.

An overlay function is handed the whole set of racks at once rather than one at a time. A
floor of fifty racks would otherwise cost fifty round trips per measure, and the power overlay
alone would issue several each. Working in one pass keeps a floor to a bounded number of
queries whatever its size.
"""

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from netbox.plugins import get_plugin_config

from netbox_spatial_lens.palette import COOLING, NO_DATA, UTILISATION, utilisation_colour

__all__ = (
    'BUILTIN_OVERLAYS',
    'NO_DATA_COLOUR',
    'NO_DATA_KEY',
    'NO_DATA_LABEL',
    'UTILISATION_LEGEND',
    'BuiltinColouring',
    'Colouring',
    'LegendEntry',
    'Overlay',
    'RackValue',
    'Registry',
    'Stat',
    'band_key',
    'build_legend',
    'floor_power_utilisation',
    'floor_space_utilisation',
    'get_overlay',
    'get_overlays',
    'register_builtin_overlays',
    'register_overlay',
    'registry',
    'resolve_colouring',
    'resolve_overlay',
)

logger = logging.getLogger('netbox.plugins.netbox_spatial_lens.overlays')

# Grey, for a rack the overlay has nothing to say about. Deliberately not green: an empty
# cooling_capacity across a whole room must read as "unknown", never as "fine".
NO_DATA_COLOUR = NO_DATA
NO_DATA_LABEL = 'No data'
# The band key of the no-data entry. Not a colour and not a label, so no named band can take it.
NO_DATA_KEY = 'lens:no-data'


@dataclass
class RackValue:
    """
    What an overlay says about one rack.

    `value` is None when the overlay has no answer, which is a first-class outcome rather than
    an error: a rack with no power feeds, or a room where nobody has filled in the cooling
    capacity, must be visibly unknown.
    """

    colour: str = NO_DATA_COLOUR
    label: str = NO_DATA_LABEL
    value: float | str | None = None

    @property
    def has_data(self) -> bool:
        return self.value is not None


@dataclass
class LegendEntry:
    colour: str
    label: str
    # How many of the things on this page fall in this band. Filled in when the legend is
    # built for a particular floor or rack, so the legend doubles as a tally: which is what
    # an overlay is usually being asked, and the reason to look at one at all.
    count: int = 0
    # What picking this band matches on the drawing, as `data-band`. The colour where the
    # colours are the bands, which is every legend whose colours are chosen to be distinct. A
    # categorical legend keys on the label instead: two roles may wear one colour, and keyed on
    # the colour they were counted and picked together.
    key: str = ''

    def __post_init__(self) -> None:
        if not self.key:
            self.key = self.colour


@dataclass
class Stat:
    """
    One figure in the strip above a drawing.

    `value` is the number somebody reads at a glance and `detail` is what makes it mean
    something: "38%" alone is not an answer, "38% full" and "772U free of 1 248" is. `tone`
    names a palette band where the figure carries one, so a floor near its limit is red in the
    strip as well as on the plan.
    """

    label: str
    value: str
    detail: str = ''
    tone: str = ''


@dataclass
class Colouring:
    """
    A named way of colouring a set of things: racks on a floor, devices in a rack, sites on the
    map.

    `fn` takes the whole set and returns a dict of id to RackValue. It may return nothing for
    an item, which reads as no data. The three registries differ only in what an item's id is,
    which is `item_key`.
    """

    name: str
    label: str
    fn: Callable
    description: str = ''
    legend: list[LegendEntry] = field(default_factory=list)

    @staticmethod
    def item_key(item) -> int:
        return item.pk

    def evaluate(self, items: Iterable) -> dict[int, RackValue]:
        """
        Colour every item, and never raise.

        A broken colouring must not take the page down with it. The drawing is still worth
        looking at with one measure missing, so a failure is logged and the items render grey.
        """
        items = list(items)
        try:
            values = self.fn(items) or {}
        except Exception as e:
            logger.error(f'{type(self).__name__} "{self.name}" failed: {e}', exc_info=True)
            values = {}
        keys = [self.item_key(item) for item in items]
        return {key: values.get(key, RackValue()) for key in keys}

    def legend_for(self, values: Iterable[RackValue]) -> list[LegendEntry]:
        """
        The legend to show beside the drawing, given what it actually came back with.
        """
        return build_legend(self.legend, values)

    def band_of(self, value: RackValue) -> str:
        """
        The legend band one value falls in, as the key the legend picks it by.
        """
        return band_key(value, self.legend)


class Overlay(Colouring):
    """
    A named way of colouring the racks on a floor.
    """


def band_key(value: RackValue, declared: Sequence[LegendEntry]) -> str:
    """
    The key of the legend band a value falls in.

    A declared legend bands by colour, and its colours are distinct by construction. A derived
    one bands by label, because the colours come from the data and two names may share one.
    """
    if not value.has_data:
        return NO_DATA_KEY
    return value.colour if declared else value.label


def build_legend(declared: Sequence[LegendEntry], values: Iterable[RackValue]) -> list[LegendEntry]:
    """
    A legend with a count against every entry, and the no-data entry last.

    Shared by the floor, the rack and the map rather than written three times: the rule about
    what a legend must say, and in particular that grey is always explained, is one rule.

    An overlay that bands a number declares its entries up front, because the bands exist
    whether or not anything falls in them. A categorical one cannot: the roles, statuses and
    tenants in use are data, so those get one entry per distinct label present.

    Every entry carries a count, because the legend is usually being read as a tally: "how
    many are nearly full", "how many are still planned". Counted by band key, which is the same
    key the drawing carries, so the count and the pick always agree.
    """
    values = list(values)
    tally: dict[str, int] = {}
    for value in values:
        key = band_key(value, declared)
        tally[key] = tally.get(key, 0) + 1

    if declared:
        entries = [LegendEntry(e.colour, e.label, tally.get(e.colour, 0), key=e.colour) for e in declared]
    else:
        colours: dict[str, str] = {}
        for value in values:
            if value.has_data:
                colours.setdefault(value.label, value.colour)
        entries = [LegendEntry(colours[label], label, tally[label], key=label) for label in sorted(colours)]

    return [*entries, LegendEntry(NO_DATA_COLOUR, NO_DATA_LABEL, tally.get(NO_DATA_KEY, 0), key=NO_DATA_KEY)]


def resolve_colouring(colourings: Sequence[Colouring], name: str | None, default: str | None) -> Colouring | None:
    """
    The colouring to draw with: the one named, else the default, else the first registered.

    Shared by the floor, the rack and the map rather than written three times: the map once had
    its own copy with no last step, so a deployment that switched the default colouring off got
    a map coloured by nothing while the other colourings sat on the toolbar.

    An unknown name falls back rather than raising, so a link carrying a colouring a later
    release removed, or a typo in the setting, still opens the drawing. None only when nothing
    is registered at all.
    """
    by_name = {colouring.name: colouring for colouring in colourings}
    return by_name.get(name) or by_name.get(default) or (colourings[0] if colourings else None)


@dataclass(frozen=True)
class BuiltinColouring:
    """
    A colouring that ships with the plugin, registered under its name unless the settings leave
    it out.
    """

    label: str
    fn: Callable
    description: str
    legend: Sequence[LegendEntry] = ()


@dataclass
class Registry[C: Colouring]:
    """
    The colourings of one level, by name, in registration order.

    One class for the floor, the rack and the map rather than three copies of the same
    functions: the copies had already drifted, and the map's fallback was the one that lost a
    step. A level differs only in the type of colouring it holds and the two settings it reads.
    """

    kind: type[C]
    # What a log line calls one of these.
    noun: str
    # The plugin settings naming the default colouring, and which built-ins to offer.
    default_setting: str
    builtins_setting: str
    builtins: dict[str, BuiltinColouring] = field(default_factory=dict)
    _items: dict[str, C] = field(default_factory=dict, repr=False)

    def register(
        self,
        name: str,
        label: str,
        fn: Callable,
        description: str = '',
        legend: Sequence[LegendEntry] | None = None,
    ) -> C:
        """
        Make a colouring selectable on every drawing of this level.

        `name` is the key used in the URL, so it survives in a shared link; keep it stable and
        change the label freely. A name registered twice keeps the later registration, which is
        how another plugin replaces a built-in.
        """
        if name in self._items:
            logger.warning(f'{self.noun} "{name}" is already registered; the later registration wins.')
        self._items[name] = self.kind(
            name=name,
            label=label,
            fn=fn,
            description=description,
            legend=list(legend or []),
        )
        return self._items[name]

    def all(self) -> list[C]:
        """
        Every registered colouring, in registration order.
        """
        return list(self._items.values())

    def get(self, name: str | None) -> C | None:
        """
        One colouring by name, or None.

        Callers fall back rather than raising: a link carrying a name that a later release
        removed should still open the drawing. See `resolve`.
        """
        return self._items.get(name) if name else None

    def resolve(self, name: str | None) -> C | None:
        """
        The colouring to draw with, given whatever the URL asked for. See `resolve_colouring`.
        """
        return resolve_colouring(self.all(), name, get_plugin_config('netbox_spatial_lens', self.default_setting))

    def register_builtins(self, names: Iterable[str] | None = None) -> None:
        """
        Register the built-in colourings, all of them or the named subset.

        An unrecognised name is logged and skipped rather than raised, so a typo in the plugin
        configuration cannot stop NetBox from booting.
        """
        for name in self.builtins if names is None else names:
            builtin = self.builtins.get(name)
            if builtin is None:
                logger.warning(f'Unknown built-in {self.noun.lower()} "{name}" in {self.builtins_setting}; skipped.')
                continue
            self.register(name, builtin.label, builtin.fn, description=builtin.description, legend=builtin.legend)

    def register_configured_builtins(self) -> None:
        """
        Register the built-ins the settings ask for: True for all, False for none, or a list.
        """
        selection = get_plugin_config('netbox_spatial_lens', self.builtins_setting)
        if selection:
            self.register_builtins(selection if isinstance(selection, (list, tuple, set)) else None)


# --------------------------------------------------------------------------------------
# Built-in overlays
# --------------------------------------------------------------------------------------

# Shared banding for the two "how full is it" overlays, so power and space read alike.
UTILISATION_LEGEND = [LegendEntry(colour, label) for _, colour, label in UTILISATION]


def _memoised_on_racks(racks: Sequence, attribute: str, compute: Callable) -> dict:
    """
    A per-rack answer, computed once per set of rack objects.

    The floor asks for space and power twice in one render: once for the overlay and once for
    the stat strip. The answer is stored on the rack instances themselves, which live only as
    long as the request, so it cannot go stale across requests the way a module cache would.
    """
    if racks and all(hasattr(rack, attribute) for rack in racks):
        return {rack.pk: getattr(rack, attribute) for rack in racks if getattr(rack, attribute) is not None}
    result = compute(racks)
    for rack in racks:
        setattr(rack, attribute, result.get(rack.pk))
    return result


def floor_power_utilisation(racks: Sequence) -> dict[int, tuple[float, float]]:
    """
    Allocated draw against feed capacity, per rack. See `_floor_power_utilisation`.
    """
    return _memoised_on_racks(list(racks), '_lens_power', _floor_power_utilisation)


def _floor_power_utilisation(racks: Sequence) -> dict[int, tuple[float, float]]:
    """
    Allocated draw against feed capacity, for a whole floor, in six queries.

    `Rack.get_power_utilization()` answers this for one rack in about twenty queries, so a
    floor of twenty-six cost 557 and took eight times as long as every other overlay. The
    arithmetic is not the expensive part; walking it one object at a time is.

    This is the same chain NetBox walks, done in sets:

        feed (capacity) -> PDU inlet -> that PDU's outlets -> the ports plugged into them

    A rack's allocated draw is the sum of `allocated_draw` over the ports at the end of that
    chain, which is what `PowerPort.get_power_draw()` returns for a PDU inlet. Restating it
    here is a deliberate exception to leaving NetBox's arithmetic alone, and it is confined to
    this one function so there is a single place to check it against upstream.

    Returns rack id to (allocated watts, capacity watts). A rack with no feeds is absent, which
    is what lets the overlay tell "no supply recorded" from "supplied and idle".
    """
    from dcim.models import PowerFeed, PowerOutlet, PowerPort

    from netbox_spatial_lens.cabling import load_objects, peer_ends

    rack_ids = [r.pk for r in racks]
    feeds = list(
        PowerFeed.objects.filter(rack_id__in=rack_ids).values('rack_id', 'available_power', 'cable_id', 'cable_end')
    )
    if not feeds:
        return {}

    capacity = {}
    for feed in feeds:
        capacity[feed['rack_id']] = capacity.get(feed['rack_id'], 0) + (feed['available_power'] or 0)

    # feed -> the PDU inlet it supplies
    inlet_peers = peer_ends({f['cable_id']: f['cable_end'] for f in feeds if f['cable_id']})
    load_objects(inlet_peers.values())

    rack_by_inlet_device = {}
    for feed in feeds:
        end = inlet_peers.get(feed['cable_id'])
        if end is not None and isinstance(end.obj, PowerPort) and end.device_id:
            rack_by_inlet_device[end.device_id] = feed['rack_id']

    # that PDU's outlets -> the ports plugged into them
    outlets = list(
        PowerOutlet.objects.filter(device_id__in=rack_by_inlet_device).values('device_id', 'cable_id', 'cable_end')
    )
    draw_peers = peer_ends({o['cable_id']: o['cable_end'] for o in outlets if o['cable_id']})

    downstream_ids = {end.object_id for end in draw_peers.values()}
    allocated_by_port = dict(PowerPort.objects.filter(pk__in=downstream_ids).values_list('pk', 'allocated_draw'))

    allocated = {}
    for outlet in outlets:
        end = draw_peers.get(outlet['cable_id'])
        if end is None:
            continue
        rack_id = rack_by_inlet_device.get(outlet['device_id'])
        if rack_id is None:
            continue
        allocated[rack_id] = allocated.get(rack_id, 0) + (allocated_by_port.get(end.object_id) or 0)

    return {rack_id: (allocated.get(rack_id, 0), watts) for rack_id, watts in capacity.items() if watts}


def power_overlay(racks: Sequence) -> dict[int, RackValue]:
    """
    Allocated draw against the capacity of the feeds supplying each rack.

    A rack with no feeds recorded is absent from the result and therefore reads as no data,
    which is the distinction that matters: "supplied and idle" and "nobody has recorded the
    supply" are different answers and both look like zero.

    The label names the capacity as well as the percentage, because a rack at 60% of 3 kW and
    one at 60% of 30 kW are not the same rack.
    """
    values = {}
    for rack_id, (allocated, capacity) in floor_power_utilisation(racks).items():
        percent = allocated / capacity * 100
        values[rack_id] = RackValue(
            colour=utilisation_colour(percent),
            label=f'{percent:.0f}% of {capacity / 1000:g} kW',
            value=percent,
        )
    return values


COOLING_LEGEND = [LegendEntry(colour, label) for colour, label in COOLING.values()]
COOLING_COLOURS = {name: colour for name, (colour, _) in COOLING.items()}


def cooling_overlay(racks: Sequence) -> dict[int, RackValue]:
    """
    Cooling capability, with the capacity in the label where it is recorded.

    Capability and capacity are separate fields and are filled in independently, so a rack can
    declare it is liquid-capable without anybody stating how much heat it can shed. Colour
    follows capability, which is the field that is usually set; capacity is reported in the
    label rather than banded, because a kW figure means nothing without knowing the room.
    """
    values = {}
    for rack in racks:
        if not rack.cooling_capability:
            continue
        label = rack.get_cooling_capability_display()
        if rack.cooling_capacity:
            label = f'{label}, {rack.cooling_capacity:g} kW'
        values[rack.pk] = RackValue(
            colour=COOLING_COLOURS.get(rack.cooling_capability, NO_DATA_COLOUR),
            label=label,
            value=rack.cooling_capability,
        )
    return values


def floor_space_utilisation(racks: Sequence) -> dict[int, tuple[float, float]]:
    """
    Occupied units against total units, per rack. See `_floor_space_utilisation`.
    """
    return _memoised_on_racks(list(racks), '_lens_space', _floor_space_utilisation)


def _floor_space_utilisation(racks: Sequence) -> dict[int, tuple[float, float]]:
    """
    Occupied units against total units, for a whole floor, in two queries.

    `Rack.get_utilization()` answers this for one rack and costs a query or three doing it, so
    a floor of twenty-six racks spent seventy-nine queries where the power overlay beside it
    spent seven. The arithmetic is the same as NetBox's; only the walk is different.

    NetBox counts a reserved unit as used, which is the honest answer to "can I put something
    here": a reserved U is not space you may take. Both halves are therefore summed.

    Returns rack id to (used units, total units). A rack with no height is absent, which is
    what lets the overlay tell "empty" from "nobody recorded how big this is".
    """
    from dcim.models import Device, RackReservation

    heights = {r.pk: float(r.u_height) for r in racks if r.u_height}
    if not heights:
        return {}

    # Half units, because NetBox works in them: a 48U rack has 96, and a device can sit on a
    # half. Held as a set per rack so a unit that is both occupied and reserved is counted
    # once, which is the difference between agreeing with `Rack.get_utilization()` and being
    # a unit adrift on any rack where somebody reserved the space they then filled.
    taken: dict[int, set] = {rack_id: set() for rack_id in heights}

    # Mounted devices. `position` is null for anything not bolted at a U, and a child device
    # in a chassis is excluded exactly as NetBox excludes it from its own figure.
    #
    # So is a device whose type is marked "exclude from utilization". NetBox's own figure asks
    # for that (`get_utilization` passes `ignore_excluded_devices=True`), which is how a shelf
    # or a blanking panel stays out of the count. Leaving it in made this plan disagree with
    # the rack's own page, and with the rack view in this plugin, which asks NetBox directly.
    rows = (
        Device.objects.filter(rack_id__in=heights, position__isnull=False)
        .exclude(parent_bay__isnull=False)
        .exclude(device_type__exclude_from_utilization=True)
        .values_list('rack_id', 'position', 'device_type__u_height')
    )
    for rack_id, position, u_height in rows:
        start = float(position)
        for step in range(int(float(u_height or 0) * 2)):
            taken[rack_id].add(start + step * 0.5)

    # Reserved units, which NetBox counts as used: a reserved U is not space you may take.
    for rack_id, units in RackReservation.objects.filter(rack_id__in=heights).values_list('rack_id', 'units'):
        for unit in units or ():
            taken[rack_id].add(float(unit))
            taken[rack_id].add(float(unit) + 0.5)

    return {rack_id: (min(len(taken[rack_id]) / 2, total), total) for rack_id, total in heights.items()}


def space_overlay(racks: Sequence) -> dict[int, RackValue]:
    """
    Occupied U against total U.

    The label names the units as well as the percentage: 60% of a 12U cabinet and 60% of a 48U
    one leave very different amounts of room, and only one of the two numbers says which.
    """
    values = {}
    for rack_id, (used, total) in floor_space_utilisation(racks).items():
        percent = used / total * 100 if total else 0
        values[rack_id] = RackValue(
            colour=utilisation_colour(percent),
            label=f'{percent:.0f}% used, {total - used:g}U free of {total:g}',
            value=percent,
        )
    return values


def role_overlay(racks: Sequence) -> dict[int, RackValue]:
    """
    The rack's own role colour, which is the one colouring an operator already knows.
    """
    values = {}
    for rack in racks:
        if not rack.role:
            continue
        values[rack.pk] = RackValue(
            colour=f'#{rack.role.color}',
            label=rack.role.name,
            value=rack.role.name,
        )
    return values


BUILTIN_OVERLAYS = {
    'power': BuiltinColouring(
        'Power',
        power_overlay,
        'How close each rack is to the capacity of the feeds supplying it.',
        UTILISATION_LEGEND,
    ),
    'cooling': BuiltinColouring(
        'Cooling',
        cooling_overlay,
        'What each rack can be cooled by, and how much heat it can shed.',
        COOLING_LEGEND,
    ),
    'space': BuiltinColouring('Space', space_overlay, 'How much of each rack is filled.', UTILISATION_LEGEND),
    'role': BuiltinColouring('Role', role_overlay, 'The rack role, in its own colour.'),
}

# The floor's colourings. The functions below are the names other plugins register with.
registry = Registry(
    kind=Overlay,
    noun='Overlay',
    default_setting='default_overlay',
    builtins_setting='enable_builtin_overlays',
    builtins=BUILTIN_OVERLAYS,
)
register_overlay = registry.register
get_overlays = registry.all
get_overlay = registry.get
resolve_overlay = registry.resolve
register_builtin_overlays = registry.register_builtins
