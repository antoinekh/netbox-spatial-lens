"""
The colourings of the racks on a floor.

Each recolours every rack by one measure: how close it is to its power limit, whether it can
take liquid cooling, how much U-space is left, what its role is, whether its devices depend on
one power feed. The floor is the same picture each time; only the colouring changes.

The two measuring functions are also what the figures above the floor are computed from.
"""

from collections.abc import Callable, Sequence

from netbox_spatial_lens.colouring import COOLING, REDUNDANCY, UTILISATION, Band, Context, Level, Reading, builtin

__all__ = (
    'floor_power_utilisation',
    'floor_space_utilisation',
)


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
    Allocated draw against feed capacity, for a whole floor, in a bounded number of queries.

    `Rack.get_power_utilization()` answers this for one rack in about twenty queries, so a
    floor of twenty-six cost 557 and took eight times as long as every other overlay. The
    arithmetic is not the expensive part; walking it one object at a time is.

    This is the same chain NetBox walks, done in sets:

        feed (capacity) -> the PDU inlet it supplies -> what that inlet draws

    What an inlet draws is `PowerPort.get_power_draw()`, resolved for every inlet at once: the
    draw it declares, or the sum of the ports plugged into its own outlets, through any PDU
    chained below. The cost follows the depth of the power chain, not the number of racks.

    Returns rack id to (allocated watts, capacity watts). A rack with no feeds is absent, which
    is what lets the overlay tell "no supply recorded" from "supplied and idle".
    """
    from dcim.models import PowerFeed, PowerPort
    from django.contrib.contenttypes.models import ContentType

    from netbox_spatial_lens.cabling import peer_ends
    from netbox_spatial_lens.power import resolve_draws

    rack_ids = [r.pk for r in racks]
    feeds = list(
        PowerFeed.objects.filter(rack_id__in=rack_ids).values('rack_id', 'available_power', 'cable_id', 'cable_end')
    )
    if not feeds:
        return {}

    capacity = {}
    for feed in feeds:
        capacity[feed['rack_id']] = capacity.get(feed['rack_id'], 0) + (feed['available_power'] or 0)

    inlet_peers = peer_ends({f['cable_id']: f['cable_end'] for f in feeds if f['cable_id']})
    port_type = ContentType.objects.get_for_model(PowerPort).pk
    inlets_by_rack: dict[int, set[int]] = {}
    for feed in feeds:
        end = inlet_peers.get(feed['cable_id'])
        if end is not None and end.type_id == port_type:
            inlets_by_rack.setdefault(feed['rack_id'], set()).add(end.object_id)

    draws = resolve_draws({inlet for inlets in inlets_by_rack.values() for inlet in inlets})
    allocated = {rack_id: sum(draws[inlet][0] for inlet in inlets) for rack_id, inlets in inlets_by_rack.items()}

    return {rack_id: (allocated.get(rack_id, 0), watts) for rack_id, watts in capacity.items() if watts}


@builtin(
    Level.RACKS,
    'power',
    label='Power',
    description='How close each rack is to the capacity of the feeds supplying it.',
    bands=UTILISATION,
)
def power(racks: Sequence, context: Context) -> dict[int, Reading]:
    """
    Allocated draw against the capacity of the feeds supplying each rack.

    A rack with no feeds recorded is absent from the result and therefore reads as no data,
    which is the distinction that matters: "supplied and idle" and "nobody has recorded the
    supply" are different answers and both look like zero.

    The label names the capacity as well as the percentage, because a rack at 60% of 3 kW and
    one at 60% of 30 kW are not the same rack.
    """
    readings = {}
    for rack_id, (allocated, capacity) in floor_power_utilisation(racks).items():
        percent = allocated / capacity * 100
        readings[rack_id] = UTILISATION.reading(percent, f'{percent:.0f}% of {capacity / 1000:g} kW')
    return readings


@builtin(
    Level.RACKS,
    'cooling',
    label='Cooling',
    description='What each rack can be cooled by, and how much heat it can shed.',
    bands=COOLING,
)
def cooling(racks: Sequence, context: Context) -> dict[int, Reading]:
    """
    Cooling capability, with the capacity in the label where it is recorded.

    Capability and capacity are separate fields and are filled in independently, so a rack can
    declare it is liquid-capable without anybody stating how much heat it can shed. The band
    follows capability, which is the field that is usually set; capacity is reported in the
    label rather than banded, because a kW figure means nothing without knowing the room.
    """
    readings = {}
    for rack in racks:
        if not rack.cooling_capability:
            continue
        label = rack.get_cooling_capability_display()
        if rack.cooling_capacity:
            label = f'{label}, {rack.cooling_capacity:g} kW'
        readings[rack.pk] = Reading(label, band=rack.cooling_capability)
    return readings


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


@builtin(Level.RACKS, 'space', label='Space', description='How much of each rack is filled.', bands=UTILISATION)
def space(racks: Sequence, context: Context) -> dict[int, Reading]:
    """
    Occupied U against total U.

    The label names the units as well as the percentage: 60% of a 12U cabinet and 60% of a 48U
    one leave very different amounts of room, and only one of the two numbers says which.
    """
    readings = {}
    for rack_id, (used, total) in floor_space_utilisation(racks).items():
        percent = used / total * 100 if total else 0
        readings[rack_id] = UTILISATION.reading(percent, f'{percent:.0f}% used, {total - used:g}U free of {total:g}')
    return readings


@builtin(Level.RACKS, 'role', label='Role', description='The rack role, in its own colour.')
def role(racks: Sequence, context: Context) -> dict[int, Reading]:
    """
    The rack's own role colour, which is the one colouring an operator already knows.
    """
    return {rack.pk: Reading(rack.role.name, colour=f'#{rack.role.color}') for rack in racks if rack.role}


# The same three states as a device has, said of the devices of a rack.
RACK_REDUNDANCY = tuple(
    Band(label, band.colour, key=band.key)
    for band, label in zip(
        REDUNDANCY,
        ('All on two or more feeds', 'Some with no feed traced', 'Some on one feed'),
        strict=True,
    )
)


@builtin(
    Level.RACKS,
    'redundancy',
    label='Redundancy',
    description='Whether a device in each rack depends on a single power feed.',
    bands=RACK_REDUNDANCY,
)
def redundancy(racks: Sequence, context: Context) -> dict[int, Reading]:
    """
    Whether a device in each rack depends on a single power feed.

    Counted over the devices, not over the feeds of the rack: a rack with two feeds and a server
    cabled to one of them loses that server with the feed, and a count of feeds calls it safe.
    The worst device decides the band, and the label says how many there are.

    A rack where no device has a power port is absent, and so reads as no data.
    """
    from dcim.models import Device

    from netbox_spatial_lens.power import load_device_power

    devices = list(Device.objects.filter(rack_id__in=[rack.pk for rack in racks]).only('pk', 'rack_id'))
    power = load_device_power(devices, totals=False)

    tally: dict[int, dict[str, int]] = {}
    for device in devices:
        state = power[device.pk].redundancy if device.pk in power else None
        if state is not None:
            counts = tally.setdefault(device.rack_id, {band.key: 0 for band in REDUNDANCY})
            counts[state] += 1

    readings = {}
    for rack_id, counts in tally.items():
        total = sum(counts.values())
        # The bands are listed with the worst last.
        worst = next(band.key for band in reversed(REDUNDANCY) if counts[band.key])
        parts = []
        if counts['single']:
            parts.append(f'{counts["single"]} of {total} devices on one feed')
        if counts['untraced']:
            parts.append(f'{counts["untraced"]} of {total} with no feed traced')
        label = ', '.join(parts) or f'{total} of {total} devices on two or more feeds'
        readings[rack_id] = Reading(label, band=worst)
    return readings
