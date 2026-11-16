"""
Colourings: one named way of colouring a set of things, on every level of the plugin.

A drawing is the same picture each time; only the colouring changes. Four sets of things are
coloured, the levels: the racks on a floor, the devices in a rack, the sites on the map and the
circuits between them. All four work the same way and are held in one registry.

A colouring is a function. It is handed the whole set at once, with the context it is asked in,
and returns a reading for each item it has an answer for:

    @colouring(Level.RACKS, 'heat', label='Heat', bands=UTILISATION)
    def heat(racks, context):
        return {rack.pk: UTILISATION.reading(percent, f'{percent:.0f}% of capacity') ...}

The whole set, because a floor of fifty racks asked one at a time is fifty round trips per
measure. An item with no reading is no data, which is a first-class outcome: it is drawn grey
and counted, never passed off as fine.

`netbox_spatial_lens.extend` is the public face of this module. Another plugin imports from
there, and writes its colourings in a module named `spatial_lens`, which is found by itself.
"""

import logging
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from importlib import import_module

from django.apps import apps
from django.utils.module_loading import module_has_submodule
from django.utils.text import slugify
from netbox.plugins import get_plugin_config

from netbox_spatial_lens.palette import COMPLETION as COMPLETION_COLOURS
from netbox_spatial_lens.palette import COOLING as COOLING_COLOURS
from netbox_spatial_lens.palette import NO_DATA as NO_DATA_COLOUR
from netbox_spatial_lens.palette import REDUNDANCY as REDUNDANCY_COLOURS
from netbox_spatial_lens.palette import RESERVED_COLOURS, distinct_colours
from netbox_spatial_lens.palette import UTILISATION as UTILISATION_COLOURS

__all__ = (
    'COMPLETION',
    'COOLING',
    'DISCOVERED_MODULE',
    'NO_DATA_COLOUR',
    'NO_DATA_KEY',
    'NO_DATA_LABEL',
    'NO_READING',
    'REDUNDANCY',
    'UTILISATION',
    'Band',
    'Colouring',
    'Context',
    'LegendEntry',
    'Level',
    'Reading',
    'Registry',
    'Scale',
    'builtin',
    'by_name',
    'colouring',
    'registry',
)

logger = logging.getLogger('netbox.plugins.netbox_spatial_lens.colouring')

NO_DATA_LABEL = 'No data'
# The band key of the no-data entry. Not a colour and not a label, so no named band can take it.
NO_DATA_KEY = 'lens:no-data'
# The module of an installed app that holds its colourings, imported the first time one is needed.
DISCOVERED_MODULE = 'spatial_lens'
# The modules of this plugin that declare its own colourings.
BUILTIN_MODULES = ('rack_colourings', 'device_colourings', 'site_colourings', 'circuit_colourings')


class Level(str, Enum):
    """
    What a colouring colours. The value is the name used in the settings and in a legend filter.
    """

    RACKS = 'racks'
    DEVICES = 'devices'
    SITES = 'sites'
    CIRCUITS = 'circuits'

    @property
    def singular(self) -> str:
        return self.value[:-1]

    @property
    def builtins_setting(self) -> str:
        """The setting that says which built-in colourings of this level are offered."""
        return f'builtin_{self.singular}_colourings'

    @property
    def default_setting(self) -> str:
        """The setting that names the colouring a page opens with."""
        return f'default_{self.singular}_colouring'


@dataclass(frozen=True)
class Band:
    """
    One entry of a legend that is known before the data is: "90% and over", "Liquid only".

    `key` is what a reading names to fall in this band, and what a shared link carries, so it
    must stay stable; the label and the colour may change freely. It is the label as a slug
    unless given.
    """

    label: str
    colour: str
    key: str = ''

    def __post_init__(self) -> None:
        if not self.key:
            object.__setattr__(self, 'key', slugify(self.label) or self.label)


@dataclass
class Reading:
    """
    What a colouring says about one item.

    `label` is the sentence in the item's hover card: "62% of 8 kW", "Support ends 2030-09-24".

    A colouring with declared bands names the band the item falls in with `band`, and the band
    gives the colour. A colouring without bands is categorical: its legend has one entry per
    distinct label, and `colour` may be left empty to get a colour no other label wears.

    `gauge` is a fraction from 0 to 1, for a reading that measures a quantity. The racks on a
    floor draw it as a gauge and print it as a percentage; the other levels ignore it.

    `facts` are more lines for the hover card, as (label, text) pairs, shown while this
    colouring is the one drawn.
    """

    label: str
    band: str = ''
    colour: str = ''
    gauge: float | None = None
    facts: Sequence[tuple[str, str]] = ()
    # False only for `NO_READING`, the answer for an item its colouring said nothing about.
    has_data: bool = True


NO_READING = Reading(label=NO_DATA_LABEL, band=NO_DATA_KEY, colour=NO_DATA_COLOUR, has_data=False)


class Scale(tuple):
    """
    The bands of a quantity, lowest first: a number falls in the first band whose limit it is
    under, and the last band has no limit.

        Scale((50, Band('Under 50%', green)), (None, Band('50% and over', red)))

    Passed as the `bands` of a colouring, it is its legend.
    """

    def __new__(cls, *steps: tuple[float | None, Band]):
        scale = super().__new__(cls, (band for _, band in steps))
        scale.limits = tuple(limit for limit, _ in steps)
        return scale

    def band(self, number: float) -> Band:
        """The band a number falls in."""
        for limit, band in zip(self.limits, self, strict=True):
            if limit is None or number < limit:
                return band
        return self[-1]

    def reading(self, percent: float, label: str, **more) -> Reading:
        """A reading for a percentage: its band on this scale, and its gauge."""
        return Reading(label, band=self.band(percent).key, gauge=max(0.0, min(1.0, percent / 100)), **more)


# The plugin's own scales and bands, so a colouring from another plugin reads like a built-in one.

# How full: power, space, heat.
UTILISATION = Scale(*((limit, Band(label, colour)) for limit, colour, label in UTILISATION_COLOURS))
# How complete: nought and one hundred are bands of their own, because a rack with one port
# cabled is not "nothing cabled" and one with a single port left is not finished.
COMPLETION = Scale(
    (1e-9, Band(COMPLETION_COLOURS[0][2], COMPLETION_COLOURS[0][1])),
    *((limit, Band(label, colour)) for limit, colour, label in COMPLETION_COLOURS[1:]),
)
COOLING = tuple(Band(label, colour, key=key) for key, (colour, label) in COOLING_COLOURS.items())
# How many power feeds a device reaches, worst last.
REDUNDANCY = tuple(Band(label, colour, key=key) for key, colour, label in REDUNDANCY_COLOURS)


@dataclass(frozen=True)
class Context:
    """
    Where a colouring is being asked, handed to its function with the items.

    `user` is the reader, or None when nobody is logged in to ask, as in a management command.
    The items handed over are already the ones the reader may view. A function that reads other
    objects restricts them with `visible`, so a label never names what the reader may not see.

    `scope` is what the drawing is of: the `Floor` for racks, the `Rack` for devices, and None
    on the map.

    `mounted` is for the devices level only: what the rack view already knows of each device,
    by device id, with `port_count`, `connected_count` and `power`, so a colouring does not
    read them a second time.
    """

    level: Level
    user: object = None
    scope: object = None
    mounted: Mapping[int, object] = field(default_factory=dict)

    def visible(self, queryset):
        """`queryset`, narrowed to what the reader may view."""
        return queryset.restrict(self.user, 'view') if self.user is not None else queryset


@dataclass
class LegendEntry:
    """
    One row of a legend as it is shown: a swatch, a label and how many fall in it.

    `key` is what picking the row matches on the drawing, as `data-band`, and what a shared
    link carries. A name, never the colour: two roles may wear one colour, and a link keyed on
    a colour stops working the day the palette changes. The colour only when nothing names it.
    """

    colour: str
    label: str
    count: int = 0
    key: str = ''

    def __post_init__(self) -> None:
        if not self.key:
            self.key = self.colour


@dataclass
class Colouring:
    """
    A named way of colouring the items of one level.

    `name` is the key used in the URL, so it survives in a shared link: keep it stable and
    change the label freely. `fn(items, context)` returns a mapping of item id to `Reading`.
    """

    level: Level
    name: str
    label: str
    fn: Callable
    description: str = ''
    bands: Sequence[Band] = ()

    def evaluate(self, items: Iterable, **context) -> dict[int, Reading]:
        """
        A reading for every item, and never an exception.

        A broken colouring must not take the page down with it. The drawing is still worth
        looking at with one measure missing, so a failure is logged and the items are no data.
        `context` is what `Context` holds besides the level.
        """
        items = list(items)
        try:
            given = self.fn(items, Context(level=self.level, **context)) or {}
            readings = self._resolve(given)
        except Exception as e:
            logger.error(f'Colouring "{self.name}" of the {self.level.value} failed: {e}', exc_info=True)
            readings = {}
        return {item.pk: readings.get(item.pk, NO_READING) for item in items}

    def _resolve(self, given: Mapping[int, Reading]) -> dict[int, Reading]:
        """
        Give every reading the band and the colour it is drawn with.

        With declared bands, the band a reading names gives its colour. Without, the label is
        the band, and the labels that came with no colour are given distinct ones, chosen
        across the whole set: the only place two names hashing alike can be seen and settled.
        """
        given = {key: reading for key, reading in given.items() if reading is not None}
        if self.bands:
            colours = {band.key: band.colour for band in self.bands}
            unknown = {reading.band for reading in given.values()} - colours.keys()
            if unknown:
                logger.warning(
                    f'Colouring "{self.name}" of the {self.level.value} named bands it does not declare: '
                    f'{", ".join(sorted(map(str, unknown)))}. Those items are drawn as no data.'
                )
            return {
                key: replace(reading, colour=colours[reading.band])
                for key, reading in given.items()
                if reading.band in colours
            }

        taken = {reading.colour for reading in given.values() if reading.colour}
        chosen = distinct_colours(
            (reading.label for reading in given.values() if not reading.colour),
            reserved=(*RESERVED_COLOURS, *taken),
        )
        return {
            key: replace(reading, band=reading.band or reading.label, colour=reading.colour or chosen[reading.label])
            for key, reading in given.items()
        }

    def legend(self, readings: Iterable[Reading]) -> list[LegendEntry]:
        """
        The legend to show beside the drawing, with a count against every entry and the
        no-data entry last.

        Declared bands are listed whether or not anything falls in them, because the bands are
        the scale. A categorical colouring cannot: the roles, statuses and tenants in use are
        data, so it gets one entry per distinct band present, in label order.

        Every entry carries a count, because a legend is usually read as a tally: "how many
        are nearly full", "how many are still planned". Counted by band key, the same key the
        drawing carries, so the count and the pick always agree.
        """
        readings = list(readings)
        tally: dict[str, int] = {}
        for reading in readings:
            tally[reading.band] = tally.get(reading.band, 0) + 1

        if self.bands:
            entries = [
                LegendEntry(band.colour, band.label, tally.get(band.key, 0), key=band.key) for band in self.bands
            ]
        else:
            shown: dict[str, Reading] = {}
            for reading in readings:
                if reading.has_data:
                    shown.setdefault(reading.band, reading)
            entries = [
                LegendEntry(reading.colour, reading.label, tally[key], key=key)
                for key, reading in sorted(shown.items(), key=lambda pair: pair[1].label)
            ]
        return [*entries, LegendEntry(NO_DATA_COLOUR, NO_DATA_LABEL, tally.get(NO_DATA_KEY, 0), key=NO_DATA_KEY)]


def by_name(items: Iterable, attribute: str) -> dict[int, Reading]:
    """
    A reading for each item that has the related object `attribute`, labelled with its name.

    For a categorical colouring by a relation: the tenant of a site, the provider of a circuit.
    """
    return {item.pk: Reading(related.name) for item in items if (related := getattr(item, attribute, None)) is not None}


class Registry:
    """
    Every colouring, by level and name, in registration order.

    Filled the first time it is read, not when the plugin starts: by then every app is loaded,
    so the built-ins the settings ask for are registered, and then the `spatial_lens` module of
    each installed app is imported, whatever the order of the plugins. A name registered twice
    keeps the later registration, which is how another plugin replaces a built-in.
    """

    def __init__(self) -> None:
        self._items: dict[Level, dict[str, Colouring]] = {level: {} for level in Level}
        self._builtins: dict[Level, dict[str, Colouring]] = {level: {} for level in Level}
        self._loaded = False
        self._lock = threading.RLock()

    def register(self, item: Colouring) -> Colouring:
        """
        Make a colouring selectable on every drawing of its level.

        The built-ins are registered first, whenever this is called, so a colouring registered
        under the name of a built-in replaces it.
        """
        self.load()
        return self._add(item)

    def _add(self, item: Colouring) -> Colouring:
        level = self._items[item.level]
        if item.name in level:
            logger.warning(
                f'Colouring "{item.name}" of the {item.level.value} is already registered; the later registration wins.'
            )
            # Moved to the end, as a new registration is.
            del level[item.name]
        level[item.name] = item
        return item

    def builtin(self, item: Colouring) -> Colouring:
        """
        Hold a colouring that ships with the plugin, registered unless the settings leave it out.
        """
        self._builtins[item.level][item.name] = item
        return item

    def load(self) -> None:
        """
        Register the built-ins the settings ask for, then whatever the installed apps declare.
        """
        with self._lock:
            if self._loaded:
                return
            # Set first: a `spatial_lens` module that reads the registry while it is imported
            # must not start a second load.
            self._loaded = True
            for module in BUILTIN_MODULES:
                import_module(f'netbox_spatial_lens.{module}')
            for level in Level:
                self._register_builtins(level)
            for app in apps.get_app_configs():
                if not module_has_submodule(app.module, DISCOVERED_MODULE):
                    continue
                # One broken extension must not take the colourings of every other plugin with it.
                try:
                    import_module(f'{app.name}.{DISCOVERED_MODULE}')
                except Exception as e:
                    logger.error(f'The colourings of {app.name} could not be loaded: {e}', exc_info=True)

    def reload(self) -> None:
        """
        Forget every registration and load again, for a test that changes the settings.
        """
        with self._lock:
            for level in Level:
                self._items[level].clear()
            self._loaded = False
            self.load()

    def _register_builtins(self, level: Level) -> None:
        """
        True for every built-in, False for none, or a list of names. An unknown name is logged
        and skipped, so a typo in the plugin configuration cannot stop NetBox from starting.
        """
        selection = get_plugin_config('netbox_spatial_lens', level.builtins_setting)
        if not selection:
            return
        builtins = self._builtins[level]
        names = selection if isinstance(selection, (list, tuple, set)) else builtins
        for name in names:
            if name not in builtins:
                logger.warning(f'Unknown built-in colouring "{name}" in {level.builtins_setting}; skipped.')
                continue
            self._add(builtins[name])

    def all(self, level: Level) -> list[Colouring]:
        """
        Every colouring of a level, in registration order.
        """
        self.load()
        return list(self._items[level].values())

    def get(self, level: Level, name: str | None) -> Colouring | None:
        """
        One colouring by name, or None.
        """
        self.load()
        return self._items[level].get(name) if name else None

    def resolve(self, level: Level, name: str | None) -> Colouring | None:
        """
        The colouring to draw with: the one named, else the default from the settings, else the
        first registered.

        An unknown name falls back rather than raising, so a link carrying a colouring a later
        release removed, or a typo in the setting, still opens the drawing. None only when
        nothing is registered at all.
        """
        default = get_plugin_config('netbox_spatial_lens', level.default_setting)
        everything = self.all(level)
        return self.get(level, name) or self.get(level, default) or (everything[0] if everything else None)


registry = Registry()


def _declare(level: Level, name: str, label: str, description: str, bands: Sequence[Band], keep: Callable) -> Callable:
    def decorate(fn: Callable) -> Callable:
        keep(Colouring(level=level, name=name, label=label, fn=fn, description=description, bands=tuple(bands)))
        return fn

    return decorate


def colouring(level: Level, name: str, *, label: str, description: str = '', bands: Sequence[Band] = ()) -> Callable:
    """
    Register the decorated function as a colouring of `level`.

    `label` is the button text and `description` its tooltip. `bands` is the legend when it is
    known before the data: a `Scale`, or a sequence of `Band`. Without it the colouring is
    categorical, and its legend is built from the labels of its readings.
    """
    return _declare(level, name, label, description, bands, registry.register)


def builtin(level: Level, name: str, *, label: str, description: str = '', bands: Sequence[Band] = ()) -> Callable:
    """
    Declare the decorated function as a colouring that ships with the plugin.
    """
    return _declare(level, name, label, description, bands, registry.builtin)
