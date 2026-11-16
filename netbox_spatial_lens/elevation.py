"""
The inside of a rack, as data.

Where each device sits, what reserved and free space there is, and every cable leaving a device
in the rack, in rack units. `scene` turns this into the 3D drawing; the stat strip, the port
allocation and the cabling list read it directly. Keeping the rack's facts apart from the
drawing is what lets the arithmetic that decides where a device sits test without a browser.

What a device holds is not this module's business. Ports live in `ports`, power in `power`, and
cables in `cabling`; this assembles their answers per device.
"""

from dataclasses import dataclass, field

from dcim.models import Device

from netbox_spatial_lens.cabling import build_runs
from netbox_spatial_lens.palette import NO_ROLE
from netbox_spatial_lens.ports import load_ports
from netbox_spatial_lens.power import load_device_power

__all__ = (
    'FreeBand',
    'MountedDevice',
    'RackElevation',
    'ReservedBand',
    'build_elevation',
    'mount_device',
    'rack_summary',
    'unit_offset',
)

NO_ROLE_COLOUR = NO_ROLE


@dataclass
class MountedDevice:
    """
    One device in the rack, once, with the face it is mounted on.
    """

    device: object
    # Rack units between the bottom of the cabinet and the bottom of the device, and how many
    # units it is tall. See `unit_offset`.
    offset: float
    units: float
    colour: str
    face: str
    port_groups: list = field(default_factory=list)
    # Power, filled in alongside the ports. A device's draw is the question asked of it
    # second, right after what it is cabled to, and NetBox puts the answer on a different
    # page from the rack.
    power: object = None
    # What the device colouring said about this device, kept whole so the legend can be built
    # from the distinct answers on this rack.
    value: object = None
    # The legend band this device falls in, as the key the legend picks it by.
    band: str = ''
    # The device's value for each custom field offered as a filter (see `field_filters`).
    field_cells: list = field(default_factory=list)

    @property
    def connected_count(self) -> int:
        return sum(g.connected for g in self.port_groups)

    @property
    def port_count(self) -> int:
        return sum(g.total for g in self.port_groups)

    @property
    def label(self) -> str:
        return self.device.name or f'{self.device.device_type} (unnamed)'


@dataclass
class RackElevation:
    """
    Everything the drawing of one rack and the panels beside it need.
    """

    rack: object
    units: int
    devices: list = field(default_factory=list)
    reservations: list = field(default_factory=list)
    runs: list = field(default_factory=list)
    unplaced: list = field(default_factory=list)
    # How the rack's units are spoken for: mounted, reserved, or free, counted the way NetBox
    # counts them for its own utilisation figure so the header and that percentage cannot
    # disagree. Filled in by build_elevation, which already has the available units in hand.
    space: dict = field(default_factory=dict)
    # Runs of consecutive free units, as bands. The empty two thirds of a half-filled cabinet
    # used to be drawn as nothing at all, which is the one thing a rack drawing is asked about
    # most: what will fit.
    free: list = field(default_factory=list)


def unit_offset(rack, position: float, u_height: float) -> float:
    """
    Rack units between the bottom of the cabinet and the bottom of something `u_height` tall
    mounted at `position`.

    A rack is numbered from the bottom by default, so U1 sits on the floor of the cabinet.
    `desc_units` inverts that, which is how some vendors label a cabinet, and getting it wrong
    silently draws every device upside down in the rack.
    """
    offset = position - rack.starting_unit
    if rack.desc_units:
        return rack.u_height - offset - u_height
    return offset


def _role_colour(device) -> str:
    role = getattr(device, 'role', None)
    return f'#{role.color}' if role and role.color else NO_ROLE_COLOUR


def mount_device(rack, device) -> MountedDevice:
    """
    One device with a U position, placed in its rack in rack units.

    Public so a drawing of many racks at once, such as the floor's devices, places a device
    exactly the way the rack's own view does.
    """
    u_height = float(device.device_type.u_height or 1)
    return MountedDevice(
        device=device,
        offset=unit_offset(rack, float(device.position), u_height),
        units=u_height,
        colour=_role_colour(device),
        face=device.face or 'front',
    )


@dataclass
class ReservedBand:
    """
    A run of consecutive reserved units, as one band.

    NetBox records a reservation as a list of unit numbers, which would draw as a stack of
    separate stripes for what is really one claim. Merging the consecutive ones back into a
    band is how a reader sees "U20 to U21 is spoken for" rather than counting stripes.
    """

    reservation: object
    # Rack units from the bottom of the cabinet to the bottom of the band, and its height.
    offset: float
    units: int
    first_unit: int
    last_unit: int

    @property
    def label(self) -> str:
        span = (
            f'U{self.first_unit}' if self.first_unit == self.last_unit else f'U{self.first_unit}\u2013U{self.last_unit}'
        )
        return f'{span} reserved'


def _build_reservations(rack) -> list[ReservedBand]:
    """
    The reserved units of a rack, merged into bands.

    Reserved space is the one thing a rack drawing can be wrong about in a way that costs
    money: a unit that is claimed, or damaged, looks exactly like a free one, and somebody
    plans a device into it. `Rack.get_utilization()` already counts these as used, so leaving
    them out of the drawing made the picture disagree with the number beside it.
    """
    reserved = rack.get_reserved_units()
    if not reserved:
        return []

    bands, run = [], []
    for unit in sorted(reserved):
        if run and unit == run[-1] + 1 and reserved[unit] == reserved[run[-1]]:
            run.append(unit)
            continue
        if run:
            bands.append(run)
        run = [unit]
    if run:
        bands.append(run)

    out = []
    for units in bands:
        first, last = units[0], units[-1]
        # Placed as one object the height of the whole run, mounted at its lowest unit number,
        # so the same call places it whichever way the rack is numbered.
        out.append(
            ReservedBand(
                reservation=reserved[first],
                offset=unit_offset(rack, first, len(units)),
                units=len(units),
                first_unit=first,
                last_unit=last,
            )
        )
    return out


@dataclass
class FreeBand:
    """
    A run of consecutive empty units, as one band.

    Named with its own height, so "will a 4U chassis go in" is answered by reading rather than
    by counting rungs against the ruler. A single free unit is drawn but not labelled: there is
    no room for the text and "1U" beside a 1U gap says nothing the gap has not already said.
    """

    offset: float
    first_unit: float
    units: float

    @property
    def label(self) -> str:
        return f'{self.units:g}U free' if self.units >= 2 else ''


def _measure_space(rack, reservations) -> tuple[dict, list['FreeBand']]:
    """
    What is used, what is reserved, what is left, and where the gaps are.

    One walk for both answers. NetBox works in half units: a 48U rack has 96 of them, and a
    device can sit on a half, so counting whole units instead reported 51 free of 48. The
    arithmetic below is NetBox's own from `Rack.get_utilization`, divided back into whole units
    at the end.
    """
    from utilities.data import drange

    # Cast: NetBox returns these as Decimal, and mixing one with the 0.5 step below raises
    # rather than comparing.
    available = {float(unit) for unit in rack.get_available_units(u_height=0.5, ignore_excluded_devices=True)}
    reserved_halves = set()
    for band in reservations:
        for unit in range(band.first_unit, band.last_unit + 1):
            for half in drange(unit, unit + 1, 0.5):
                half = float(half)
                if half in available:
                    available.discard(half)
                    reserved_halves.add(half)

    total_halves = len(list(rack.units))
    space = {
        'total': rack.u_height,
        'free': len(available) / 2,
        'reserved': len(reserved_halves) / 2,
        'used': (total_halves - len(available) - len(reserved_halves)) / 2,
    }

    # Consecutive free halves, merged into bands. Sorted low to high whichever way the cabinet
    # is numbered; `unit_offset` places each band correctly from its first unit and its height.
    bands, run = [], []
    for half in sorted(available):
        if run and abs(half - run[-1] - 0.5) < 1e-6:
            run.append(half)
            continue
        if run:
            bands.append(run)
        run = [half]
    if run:
        bands.append(run)

    free = [
        FreeBand(
            offset=unit_offset(rack, halves[0], len(halves) / 2),
            first_unit=halves[0],
            units=len(halves) / 2,
        )
        for halves in bands
    ]
    return space, free


def build_elevation(rack, devices_queryset=None) -> 'RackElevation':
    """
    Lay out a rack and the cables leaving it.

    Cables are read once for the whole rack rather than per device. A rack of forty servers
    with two links each is eighty cables, and asking per device turned that into eighty
    queries for an answer one query gives.

    `devices_queryset` is what the reader may see, and the view passes its own restricted one.
    A user allowed the rack but not its contents should get the cabinet and its free space, not
    an inventory of the machines in it.
    """
    base = Device.objects.all() if devices_queryset is None else devices_queryset
    devices = list(
        base.filter(rack=rack)
        .select_related('role', 'device_type', 'device_type__manufacturer', 'tenant')
        # For the Tags finder, in one query for the rack.
        .prefetch_related('tags')
        .order_by('position')
    )

    mounted, unplaced = [], []
    for device in devices:
        if device.position is None:
            # A device in the rack but not mounted at a U, which is normal for a
            # child device in a chassis or for something simply not recorded yet.
            unplaced.append(device)
            continue
        mounted.append(mount_device(rack, device))

    ports_by_device = load_ports({m.device.pk for m in mounted})
    power_by_device = load_device_power([m.device for m in mounted])
    for m in mounted:
        m.port_groups = ports_by_device.get(m.device.pk, [])
        m.power = power_by_device.get(m.device.pk)

    # Top of the rack first, the way a cabinet is read and the cabling list is ordered.
    order = {m.device.pk: -(m.offset + m.units) for m in mounted}
    runs = build_runs(rack, devices, order, devices_queryset=devices_queryset)

    reservations = _build_reservations(rack)
    space, free = _measure_space(rack, reservations)

    return RackElevation(
        rack=rack,
        units=rack.u_height,
        devices=mounted,
        reservations=reservations,
        runs=runs,
        unplaced=unplaced,
        space=space,
        free=free,
    )


def rack_summary(elevation: 'RackElevation') -> list:
    """
    The headline figures for a rack, above the drawing.

    What is in it, what is left, what is wired and what it draws. All four had been on the page
    already, spread between a line of muted text above the cabinet, a badge on a card halfway
    down, and a panel you had to select a device to see; a reader wanting to know whether this
    cabinet had room walked away with none of them.

    Costs nothing: everything here has already been resolved to draw the elevation.
    """
    from netbox_spatial_lens.palette import utilisation_colour
    from netbox_spatial_lens.stats import Stat

    space = elevation.space
    total = space.get('total') or 0
    free = space.get('free') or 0
    reserved = space.get('reserved') or 0
    percent = (total - free) / total * 100 if total else 0

    # The tallest gap, because "30U free" spread over ten gaps of three will not take a 4U
    # chassis and the single number says it will.
    largest = max((band.units for band in elevation.free), default=0)

    external = sum(1 for run in elevation.runs if not run.internal)
    mounted = elevation.devices
    connected = sum(m.connected_count for m in mounted)
    ports = sum(m.port_count for m in mounted)

    stats = [
        Stat(
            label='Devices',
            value=str(len(mounted)),
            detail=f'{len(elevation.unplaced)} with no U recorded'
            if elevation.unplaced
            else f'{elevation.rack.u_height}U cabinet',
        ),
        Stat(
            label='Free space',
            value=f'{free:g}U',
            detail=f'largest gap {largest:g}U' + (f', {reserved:g}U reserved' if reserved else ''),
            tone=utilisation_colour(percent),
        ),
        Stat(
            label='Cabling',
            value=str(len(elevation.runs)),
            detail=f'{external} leaving the rack' if external else 'none leaving the rack',
        ),
        Stat(
            label='Free ports',
            value=f'{ports - connected}' if ports else '—',
            detail=f'of {ports}, {connected} connected' if ports else 'none recorded',
        ),
    ]
    return stats
