"""
The cables that leave a rack, and the ones that leave the room.

A rack elevation shows what is plugged into a rack; it cannot show where the other end went.
That is a floor-level question ("which cabinets does this row actually depend on", "what runs
under this aisle"), and it is the one thing a floor plan can answer that no other NetBox page
can.

One line per pair of racks, not one per cable. A pair of racks joined by forty fibres would
otherwise be forty identical overlapping lines: slow to draw, impossible to read, and no more
informative than a single line labelled forty. The count becomes the line's weight instead.

Cables with both ends in the same rack are left out; they are internal to a cabinet and the
elevation already draws them.

A cable whose far end is nowhere on this floor is not dropped, though. A branch office is one
rack and a circuit to a provider, and a plan that draws only rack-to-rack runs shows that room
as having no cabling at all, which is the opposite of the truth. Those are drawn as exits: a
stub from the rack to the nearest wall, named after whatever it reaches.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from urllib.parse import urlencode

from dcim.models import CableTermination, Rack
from django.urls import reverse

from netbox_spatial_lens.geometry import PlacedRack
from netbox_spatial_lens.overlays import LegendEntry
from netbox_spatial_lens.palette import KIND

__all__ = (
    'FloorExit',
    'FloorRun',
    'build_floor_exits',
    'build_floor_runs',
    'cabling_legend',
    'count_cables',
)

# A run is drawn in room centimetres, so these are widths on the floor rather than pixels. The
# floor is scaled to fit the page, so a one-cable run has to be visible in a large room and a
# forty-cable run must not swallow the aisle it crosses.
MIN_WIDTH = 4.0
MAX_WIDTH = 22.0
WIDTH_PER_CABLE = 1.6

# Centimetres between two stubs leaving the same rack, so a rack with three circuits shows
# three arrows rather than one drawn three times.
EXIT_SPREAD = 70.0

# How far past the wall a stub ends, as a fraction of the room's smaller dimension. The plan is
# drawn with a margin around the room for its scale, so there is space out there to end in, and
# a stub that crosses the wall reads as leaving where one that stops at it reads as arriving.
OVERSHOOT = 0.045

# What an exit reaches, and the colour it is drawn in. A circuit is the interesting one: it is
# the estate's edge, so it borrows the rack view's circuit colour and reads the same there.
# Each destination gets a colour of its own, and none of them is the colour of a rack-to-rack
# run: two lines that mean different things must never be told apart by their length alone.
EXIT_KINDS = {
    'circuit': ('To a circuit', KIND['circuit']),
    'rack': ('To a rack elsewhere', KIND['console']),
    'site': ('To another site', KIND['passthrough']),
    'other': ('Off the plan', KIND['other']),
}

# What a line between two racks on this floor is drawn in.
RUN_COLOUR = KIND['interface']


@dataclass
class FloorRun:
    """
    Every cable between two placed racks, as one line.

    `a` and `b` are the placements, so the line is drawn between rack centres and follows the
    racks when somebody drags them.
    """

    a: PlacedRack
    b: PlacedRack
    count: int

    @property
    def width(self) -> float:
        return min(MAX_WIDTH, MIN_WIDTH + (self.count - 1) * WIDTH_PER_CABLE)

    @property
    def label(self) -> str:
        cables = 'cable' if self.count == 1 else 'cables'
        return f'{self.a.rack.name} to {self.b.rack.name}: {self.count} {cables}'


def build_floor_runs(placed: Sequence[PlacedRack]) -> list[FloorRun]:
    """
    Aggregate the cabling between the racks on one floor, in a single query.

    `CableTermination` denormalises the rack each end sits in, which is what makes this cheap:
    the alternative is walking every cable's terminations to their devices to their racks, and
    that is a query per cable on a floor that may hold thousands.

    A cable with several terminations at one end (a bundle broken out across racks) counts once
    per pair of racks it actually joins, which is what somebody pulling it would see.
    """
    by_rack = {p.rack.pk: p for p in placed}
    if len(by_rack) < 2:
        return []

    ends: dict[int, dict[str, set[int]]] = {}
    # Unordered: the default ordering joins the cable table to sort rows that are summed.
    rows = (
        CableTermination.objects.filter(_rack_id__in=by_rack)
        .order_by()
        .values_list('cable_id', 'cable_end', '_rack_id')
    )
    for cable_id, cable_end, rack_id in rows:
        ends.setdefault(cable_id, {'A': set(), 'B': set()})[cable_end].add(rack_id)

    counts: dict[tuple[int, int], int] = {}
    for sides in ends.values():
        for near in sides['A']:
            for far in sides['B']:
                if near == far:
                    continue
                counts[_pair(near, far)] = counts.get(_pair(near, far), 0) + 1

    runs = [FloorRun(a=by_rack[a], b=by_rack[b], count=count) for (a, b), count in counts.items()]
    # Heaviest last, so the busiest runs are drawn on top of the ones they cross.
    runs.sort(key=lambda run: (run.count, run.a.rack.pk, run.b.rack.pk))
    return runs


def _pair(a: int, b: int) -> tuple[int, int]:
    """
    A rack pair keyed the same way whichever end the cable was walked from.
    """
    return (a, b) if a < b else (b, a)


def count_cables(runs: Iterable[FloorRun]) -> int:
    return sum(run.count for run in runs)


@dataclass
class FloorExit:
    """
    Everything leaving one rack towards one place that is not on this floor.

    The stub ends on the room's nearest wall rather than at the far end's real position: the
    far end is usually not in this room at all, and a line drawn towards where it actually is
    would claim a geography the plan does not have.
    """

    rack: PlacedRack
    label: str
    # Every cable this one stub stands for. A stub is a drawing of cabling, so clicking it has
    # to land on cabling, and that cannot be answered from a count.
    cable_ids: set[int] = field(default_factory=set)
    kind: str = 'other'
    # The far end's own page, where the far end is a thing worth opening in its own right. A
    # circuit is: the stub is labelled with its ID, so clicking it goes where the label says.
    # A rack is not, because the line drawn is the cabling, not the cabinet it happens to reach.
    far_url: str = ''
    x: float = 0.0
    y: float = 0.0
    # The dot on the wall, in room centimetres. Set when the exit is placed, because it is
    # sized against the room: a fixed radius is a blob in a comms closet and invisible in a
    # hall thirty metres across.
    radius: float = MIN_WIDTH

    @property
    def count(self) -> int:
        return len(self.cable_ids)

    @property
    def url(self) -> str:
        """
        Where clicking the stub goes.

        The far end's own page when it has one worth opening, and otherwise the cabling itself:
        the one cable where there is one, and a list of exactly these cables where there are
        several. Filtered by cable id rather than by the two racks, because a rack pair also
        matches cabling this stub never drew.
        """
        if self.far_url:
            return self.far_url
        if not self.cable_ids:
            return ''
        if len(self.cable_ids) == 1:
            return reverse('dcim:cable', args=[next(iter(self.cable_ids))])
        query = urlencode([('id', pk) for pk in sorted(self.cable_ids)])
        return f'{reverse("dcim:cable_list")}?{query}'

    @property
    def colour(self) -> str:
        return EXIT_KINDS.get(self.kind, EXIT_KINDS['other'])[1]

    @property
    def width(self) -> float:
        return min(MAX_WIDTH, MIN_WIDTH + (self.count - 1) * WIDTH_PER_CABLE)

    @property
    def title(self) -> str:
        cables = 'cable' if self.count == 1 else 'cables'
        return f'{self.rack.rack.name} to {self.label}: {self.count} {cables}'


@dataclass
class _FarEnd:
    """
    What one termination outside the floor turns out to be, resolved in bulk.
    """

    label: str
    kind: str = 'other'
    url: str = ''


def build_floor_exits(placed: Sequence[PlacedRack], floor, user=None) -> list[FloorExit]:
    """
    The cabling that leaves the room, one stub per rack per destination.

    Bounded queries, not one per cable: the terminations are read in two passes and the far
    ends are then resolved by type in one query each.

    `user` is the reader. A circuit, rack or site they may not view is not named: its stub is
    still drawn, because the cable leaves a rack they may see, and it reads "off the plan".
    """
    by_rack = {p.rack.pk: p for p in placed}
    if not by_rack:
        return []

    near = CableTermination.objects.filter(_rack_id__in=by_rack).order_by().values_list('cable_id', '_rack_id')
    cable_racks: dict[int, set[int]] = {}
    for cable_id, rack_id in near:
        cable_racks.setdefault(cable_id, set()).add(rack_id)
    if not cable_racks:
        return []

    far_rows = list(
        CableTermination.objects.filter(cable_id__in=cable_racks)
        .exclude(_rack_id__in=by_rack)
        .order_by()
        .values_list('cable_id', 'termination_type__model', 'termination_id', '_rack_id', '_site_id')
    )
    if not far_rows:
        return []

    resolved = _resolve_far_ends(far_rows, user, home_site_id=floor.effective_site.pk)

    counts: dict[tuple[int, str], FloorExit] = {}
    for cable_id, model, termination_id, _, _ in far_rows:
        end = resolved.get((model, termination_id)) or _FarEnd(label='off the plan')
        for rack_id in cable_racks[cable_id]:
            key = (rack_id, end.label)
            if key not in counts:
                counts[key] = FloorExit(
                    rack=by_rack[rack_id],
                    label=end.label,
                    kind=end.kind,
                    far_url=end.url,
                )
            counts[key].cable_ids.add(cable_id)

    exits = list(counts.values())
    _place_exits(exits, floor)
    # Heaviest last, so a busy exit is drawn over the ones it crosses.
    exits.sort(key=lambda e: (e.count, e.rack.rack.pk, e.label))
    return exits


def _restricted(queryset, user):
    return queryset if user is None else queryset.restrict(user, 'view')


def _resolve_far_ends(rows, user=None, home_site_id: int | None = None) -> dict[tuple[str, int], _FarEnd]:
    """
    Name every off-floor termination, one query per kind of thing rather than one per cable.

    Each name comes from an object the reader may view, or the far end is left unresolved.
    So is a far end in no rack of `home_site_id`, the floor's own site: it left the plan, not
    the site.
    """
    from circuits.models import Circuit, CircuitTermination
    from dcim.models import Site

    by_model: dict[str, set[int]] = {}
    rack_ids: set[int] = set()
    for _, model, termination_id, far_rack_id, _ in rows:
        by_model.setdefault(model or '', set()).add(termination_id)
        if far_rack_id:
            rack_ids.add(far_rack_id)

    resolved: dict[tuple[str, int], _FarEnd] = {}

    # A circuit is the estate's edge: name it by its ID and provider, which is what somebody
    # chasing an outage has in front of them.
    if 'circuittermination' in by_model:
        terminations = CircuitTermination.objects.filter(
            pk__in=by_model['circuittermination'], circuit__in=_restricted(Circuit.objects.all(), user)
        ).select_related('circuit', 'circuit__provider')
        for term in terminations:
            circuit = term.circuit
            provider = f' ({circuit.provider})' if circuit.provider else ''
            resolved[('circuittermination', term.pk)] = _FarEnd(
                label=f'{circuit.cid}{provider}',
                kind='circuit',
                url=circuit.get_absolute_url(),
            )

    # Anything sitting in a rack somewhere else: another room, or another site entirely.
    racks = (
        {r.pk: r for r in _restricted(Rack.objects.all(), user).filter(pk__in=rack_ids).select_related('site')}
        if rack_ids
        else {}
    )
    for _, model, termination_id, far_rack_id, _ in rows:
        key = (model, termination_id)
        if key in resolved:
            continue
        rack = racks.get(far_rack_id)
        if rack:
            resolved[key] = _FarEnd(label=f'{rack.site} · {rack.name}', kind='rack')

    # A far end with no rack at all still usually knows its site, which is enough to say the
    # cable leaves the building rather than merely the room.
    site_ids = {site_id for _, _, _, _, site_id in rows if site_id and site_id != home_site_id}
    sites = (
        dict(_restricted(Site.objects.all(), user).filter(pk__in=site_ids).values_list('pk', 'name'))
        if site_ids
        else {}
    )
    for _, model, termination_id, _, far_site_id in rows:
        key = (model, termination_id)
        if key in resolved or not far_site_id:
            continue
        name = sites.get(far_site_id)
        if name:
            resolved[key] = _FarEnd(label=str(name), kind='site')

    return resolved


def _place_exits(exits: list[FloorExit], floor) -> None:
    """
    Put each stub's far end on the wall nearest the rack it leaves.

    Several exits from one rack are spread along that wall, or they would be one line drawn on
    top of itself and the count would be the only clue that there was more than one.
    """
    width, depth = floor.width_cm, floor.depth_cm
    by_rack: dict[int, list[FloorExit]] = {}
    for item in exits:
        by_rack.setdefault(item.rack.rack.pk, []).append(item)

    for group in by_rack.values():
        # Stable order, so a redraw does not shuffle the stubs around the rack.
        group.sort(key=lambda e: e.label)
        for index, item in enumerate(group):
            offset = (index - (len(group) - 1) / 2) * EXIT_SPREAD
            item.x, item.y = _wall_point(item.rack, width, depth, offset)
            item.radius = max(item.width, min(width, depth) / 45)


def _wall_point(rack: PlacedRack, width: float, depth: float, offset: float) -> tuple[float, float]:
    """
    Where one stub ends, just outside the wall nearest its rack.

    Outside, not on: a rack standing near a wall is exactly the one whose stub had nowhere to
    go. Plant 1 sat 75 cm from the left-hand wall, so its three circuits drew three stubs
    shorter than the cabinet they left, hidden underneath it, and the plan showed three dots
    against the wall joined to nothing.

    Crossing the wall is also the truer picture. The far end of these cables is not in this
    room, and a line that stops at the wall says it arrives there.
    """
    over = OVERSHOOT * min(width, depth)
    distances = {
        'top': rack.y,
        'bottom': depth - rack.y,
        'left': rack.x,
        'right': width - rack.x,
    }
    wall = min(distances, key=distances.get)
    if wall in ('top', 'bottom'):
        return _clamp(rack.x + offset, width), -over if wall == 'top' else depth + over
    return -over if wall == 'left' else width + over, _clamp(rack.y + offset, depth)


def _clamp(value: float, limit: float) -> float:
    return max(0.0, min(value, limit))


def cabling_legend(runs: Iterable[FloorRun], exits: Iterable[FloorExit]) -> list[LegendEntry]:
    """
    What each colour on the plan means, and how many cables are in it.

    The same builder the overlays use, so the cabling reads like every other legend on the
    page. "Between racks" is listed even at zero: a plan with no line on it must say which
    line it is missing, not leave the reader to guess whether the toggle worked.
    """
    entries = [LegendEntry(RUN_COLOUR, 'Between racks', count_cables(runs))]

    by_kind: dict[str, int] = {}
    for item in exits:
        by_kind[item.kind] = by_kind.get(item.kind, 0) + item.count
    for kind, (label, colour) in EXIT_KINDS.items():
        if kind in by_kind:
            entries.append(LegendEntry(colour, label, by_kind[kind]))
    return entries
