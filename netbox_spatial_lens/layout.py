"""
Turning a floor into something drawable.

Kept out of `views` because both the page and the REST API render from it, and a view module
importing from another view module is the shape that leads to circular imports. Nothing here
touches a request: given a floor and an overlay it returns positions and colours, which is
what makes it usable from the API, from a management command, or from a future renderer.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from dcim.models import Device, Rack
from django.db.models import Count

from netbox_spatial_lens.geometry import PlacedRack, natural_key, rack_footprint_cm, size_labels
from netbox_spatial_lens.models import RackPlacement
from netbox_spatial_lens.overlays import (
    RackValue,
    Stat,
    floor_power_utilisation,
    floor_space_utilisation,
    resolve_overlay,
)
from netbox_spatial_lens.palette import utilisation_colour

__all__ = (
    'RackRow',
    'build_layout',
    'build_layouts',
    'floor_summary',
    'rack_rows',
    'resolve_overlay',
    'unplaced_racks',
)


def build_layout(floor, overlay, racks=None, devices=None) -> list[PlacedRack]:
    """
    Everything one render of a floor needs.

    The racks are fetched once, with the annotations and related objects the overlays read, so
    a floor costs a bounded number of queries rather than growing with the number of racks.
    The power overlay is the exception and says so itself.

    `racks` is the set of racks the reader may see, and the view passes its own restricted
    queryset. A placement is the plugin's own object and NetBox will happily show it; the
    cabinet on the other end of it is not, and drawing one the reader may not open would make
    the plan a way around the permissions every other page in NetBox enforces. Defaulting to
    every rack keeps the function usable from a shell or a command, where there is no user.

    `devices` is restricted the same way, for the device count on each rack: a count that
    includes devices the reader may not open says something the rack page would not.
    """
    return build_layouts([floor], overlay, racks=racks, devices=devices)[floor.pk]


def build_layouts(floors, overlay, racks=None, devices=None, measure=False) -> dict[int, list[PlacedRack]]:
    """
    The layouts of several floors, read together, keyed by floor id.

    The site page draws every room at once. Read a floor at a time, each room repeated the
    placement, device count, space and power queries, so a site of twenty rooms cost twenty
    times one. Here the placements and the device counts are one query each for every floor.

    `measure` walks space and power once over the racks of every floor before the overlay
    runs. Pass it where each floor's summary is shown, as on the site page: the overlay and
    `floor_summary` then find both answers already on the racks. A drawing that needs neither,
    such as the editor, leaves it off and does not pay for them.

    The overlay is still handed the racks of one floor at a time, which is what `extending.md`
    promises, so a colouring that compares the racks in a room keeps seeing one room.

    `racks` and `devices` restrict what is drawn, as in `build_layout`.
    """
    floors = list(floors)
    placements = (
        RackPlacement.objects.filter(floor__in=floors)
        .select_related('rack', 'rack__role', 'rack__location', 'rack__tenant')
        # For the Tags finder, the rack table and the hover card, in one query for every floor.
        .prefetch_related('rack__tags')
    )
    if racks is not None:
        placements = placements.filter(rack__in=racks)
    placements = list(placements)

    by_floor: dict[int, list[RackPlacement]] = {floor.pk: [] for floor in floors}
    for placement in placements:
        by_floor[placement.floor_id].append(placement)

    if measure:
        every_rack = [placement.rack for placement in placements]
        floor_space_utilisation(every_rack)
        floor_power_utilisation(every_rack)

    device_base = Device.objects.all() if devices is None else devices
    device_counts = dict(
        device_base.filter(rack_id__in=[p.rack_id for p in placements])
        .order_by()
        .values('rack_id')
        .annotate(n=Count('pk'))
        .values_list('rack_id', 'n')
    )

    return {
        floor_id: _place_racks(floor_placements, overlay, device_counts)
        for floor_id, floor_placements in by_floor.items()
    }


def _place_racks(placements: Sequence[RackPlacement], overlay, device_counts: dict[int, int]) -> list[PlacedRack]:
    """
    One floor's placements as racks to draw, coloured by the overlay.
    """
    values = overlay.evaluate([placement.rack for placement in placements]) if overlay else {}

    placed = []
    for placement in placements:
        width, depth, estimated = rack_footprint_cm(placement.rack)
        # No overlay, as on the editor, still yields a RackValue: the neutral one.
        value = values.get(placement.rack.pk) or RackValue()
        device_count = device_counts.get(placement.rack_id, 0)
        placed.append(
            PlacedRack(
                rack=placement.rack,
                x=float(placement.x),
                y=float(placement.y),
                rotation=float(placement.rotation),
                width=width,
                depth=depth,
                estimated=estimated,
                value=value,
                facts=_rack_facts(placement.rack, width, depth, estimated, device_count),
                band=overlay.band_of(value) if overlay else '',
                device_count=device_count,
            )
        )
    # One type size for the whole drawing, and names trimmed to the cabinets that hold them.
    size_labels(placed)
    return placed


def _rack_facts(rack, width: float, depth: float, estimated: bool, device_count: int) -> list[tuple[str, str]]:
    """
    What the hover card lists under a rack's name.

    Only what is recorded. A card padded with dashes reads as an inventory in worse shape than
    it is, and the one line that must appear whatever else is missing is the footprint, because
    a drawing that guessed the size has to say so where the reader is looking at the size.
    """
    facts = [('Height', f'{rack.u_height}U')]
    if rack.role:
        facts.append(('Role', rack.role.name))
    if rack.location:
        facts.append(('Location', str(rack.location)))
    if rack.tenant:
        facts.append(('Tenant', str(rack.tenant)))
    if rack.asset_tag:
        facts.append(('Asset tag', rack.asset_tag))
    tags = [tag.name for tag in rack.tags.all()]
    if tags:
        facts.append(('Tags', ', '.join(tags)))
    facts.append(('Devices', str(device_count)))
    facts.append(
        (
            'Footprint',
            f'{width:g} \u00d7 {depth:g} cm{" (estimated)" if estimated else ""}',
        )
    )
    return facts


def unplaced_racks(floor, racks=None):
    """
    Racks at this floor's site which nobody has placed yet.

    Visual Explorer calls this the unplaced racks panel, and it is the thing that makes an
    editor usable: it answers "what have I still to put down" without the operator holding the
    inventory in their head.

    Restricted like the plan is: a panel that offers a cabinet the reader may not see is both a
    leak and a trap, since placing it would fail on the way back in.
    """

    site = floor.effective_site
    if not site:
        return Rack.objects.none()
    base = Rack.objects.all() if racks is None else racks
    qs = base.filter(site=site, lens_placement__isnull=True)
    locations = floor.rack_locations()
    if locations is not None:
        qs = qs.filter(location__in=locations)
    return qs.select_related('role', 'location')


@dataclass
class RackRow:
    """
    One rack in the table under the plan.

    The plan answers "where"; the table answers "which is fullest", "which has no feed", "which
    holds the most devices", which on the plan means hovering every cabinet in turn. Its figures
    are the ones the overlays and the stat strip use, so the three cannot disagree.
    """

    placed: PlacedRack
    space_percent: float | None = None
    free_units: float | None = None
    power_percent: float | None = None
    # Of the feeds recorded against the rack.
    power_capacity_kw: float | None = None

    @property
    def rack(self):
        return self.placed.rack


def rack_rows(placed: Sequence[PlacedRack]) -> list[RackRow]:
    """
    The rows of the rack table, in natural name order.

    Costs nothing on a floor page: the space and power walks have already been made for the
    overlay or the stat strip, and are reused.
    """
    racks = [p.rack for p in placed]
    space = floor_space_utilisation(racks)
    power = floor_power_utilisation(racks)

    rows = []
    for p in sorted(placed, key=lambda item: natural_key(item.rack.name)):
        row = RackRow(placed=p)
        if p.rack.pk in space:
            used, total = space[p.rack.pk]
            row.space_percent = used / total * 100 if total else 0
            row.free_units = total - used
        if p.rack.pk in power:
            allocated, capacity = power[p.rack.pk]
            row.power_percent = allocated / capacity * 100
            row.power_capacity_kw = capacity / 1000
        rows.append(row)
    return rows


def floor_summary(floor, placed: Sequence[PlacedRack]) -> list[Stat]:
    """
    The headline figures for a floor, above the drawing.

    A plan answers "where"; these answer "how much", which is the question somebody usually
    arrives with. They are deliberately the same four measures the overlays colour by, so the
    strip and the plan are two readings of one set of facts rather than two sets.

    The space and power walks are the bulk ones the overlays use, and where the overlay on show
    has already walked one of them for these racks its answer is reused rather than read again.
    """
    if not placed:
        return []

    racks = [p.rack for p in placed]
    space = floor_space_utilisation(racks)
    power = floor_power_utilisation(racks)

    used = sum(u for u, _ in space.values())
    total = sum(t for _, t in space.values())
    devices = sum(p.device_count for p in placed)

    stats = [
        Stat(
            label='Racks',
            value=str(len(placed)),
            detail=f'{sum(1 for p in placed if p.estimated)} estimated footprint'
            if any(p.estimated for p in placed)
            else f'{floor.width:g} \u00d7 {floor.depth:g} {floor.get_unit_display().lower()}',
        ),
        Stat(label='Devices', value=str(devices), detail='mounted and racked'),
    ]

    if total:
        percent = used / total * 100
        stats.append(
            Stat(
                label='Space',
                value=f'{percent:.0f}%',
                detail=f'{total - used:g}U free of {total:g}',
                tone=utilisation_colour(percent),
            )
        )

    if power:
        allocated = sum(a for a, _ in power.values())
        capacity = sum(c for _, c in power.values())
        percent = allocated / capacity * 100 if capacity else 0
        stats.append(
            Stat(
                label='Power',
                value=f'{percent:.0f}%',
                detail=f'{allocated / 1000:.1f} of {capacity / 1000:.1f} kW allocated',
                tone=utilisation_colour(percent),
            )
        )
    else:
        # Named rather than dropped. A floor with no feeds recorded and a floor drawing no
        # power are the same picture, and only one of them is good news.
        stats.append(Stat(label='Power', value='—', detail='no feeds recorded'))

    return stats
