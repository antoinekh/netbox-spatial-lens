"""
Turning placements into something drawable.

A placement stores a position and an angle. How big the rack is comes from the rack itself, so
the drawing follows the inventory instead of holding a second copy of it that can drift.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from netbox.plugins import get_plugin_config

if TYPE_CHECKING:  # pragma: no cover
    from dcim.models import Rack

    from netbox_spatial_lens.models import Floor

__all__ = (
    'FloorViewport',
    'PlacedRack',
    'autoplace_racks',
    'floor_viewport',
    'metre_step',
    'metre_ticks',
    'rack_footprint_cm',
    'size_labels',
)

# NetBox stores rack outer dimensions in millimetres or inches.
MM_PER_INCH = 25.4


def rack_footprint_cm(rack: 'Rack') -> tuple[float, float, bool]:
    """
    A rack's width and depth in centimetres, and whether they were measured or assumed.

    NetBox lets a rack declare `outer_width` and `outer_depth` in either millimetres or
    inches, and most inventories leave both blank. A blank one falls back to a configured
    default so the rack can still be drawn, and the caller is told the size is an estimate
    rather than being left to present a guess as a measurement.
    """
    default_width = get_plugin_config('netbox_spatial_lens', 'default_rack_width')
    default_depth = get_plugin_config('netbox_spatial_lens', 'default_rack_depth')

    width_mm, depth_mm = rack.outer_width, rack.outer_depth
    estimated = width_mm is None or depth_mm is None

    if rack.outer_unit == 'in':
        width_mm = width_mm * MM_PER_INCH if width_mm is not None else None
        depth_mm = depth_mm * MM_PER_INCH if depth_mm is not None else None

    width_mm = float(width_mm) if width_mm is not None else default_width
    depth_mm = float(depth_mm) if depth_mm is not None else default_depth

    return width_mm / 10, depth_mm / 10, estimated


@dataclass
class PlacedRack:
    """
    One rack, ready to draw: where it is, how big it is, and what the colouring said about it.

    The colouring's result is kept whole rather than flattened into a colour and a label. The
    legend is built from the distinct results on a floor, so it needs to compare them, and a
    pair of strings pulled apart here could not be put back together reliably.
    """

    rack: object
    x: float
    y: float
    rotation: float
    width: float
    depth: float
    estimated: bool
    value: object  # colouring.Reading
    # The name's size in room centimetres, and how much of the name fits at it. Both are set
    # once for the whole floor rather than per rack: see `size_labels`.
    label_size: float = 12.0
    display_name: str = ''
    # What the hover card lists of the rack itself, as label/value pairs. Built by the layout
    # so the drawing has somewhere to read them from without a second query per rack.
    rack_facts: list = field(default_factory=list)
    # The legend band this rack falls in, as the key the legend picks it by.
    band: str = ''
    # How many devices the reader may see in this rack.
    device_count: int = 0
    # The rack's value for each custom field offered as a filter (see `field_filters`).
    field_cells: list = field(default_factory=list)

    @property
    def colour(self) -> str:
        return self.value.colour

    @property
    def label(self) -> str:
        return self.value.label

    @property
    def has_data(self) -> bool:
        return self.value.has_data

    @property
    def facts(self) -> list:
        """The lines of the hover card: what the colouring adds, then the rack's own."""
        return [*self.value.facts, *self.rack_facts]

    @property
    def fraction(self) -> float | None:
        """
        Where this rack sits between empty and full, as 0 to 1, or None when the colouring is
        not measuring a quantity. Power and space answer with one; role and cooling do not.
        """
        gauge = self.value.gauge
        return None if gauge is None else max(0.0, min(1.0, float(gauge)))

    @property
    def label_turn(self) -> int:
        """
        Degrees to turn the rack's text within its own group, so that it reads upright: the
        text turns with the rack, and a rack that faces down the plan would carry it upside down.
        """
        return 180 if 90 < self.rotation <= 270 else 0

    @property
    def gauge_label(self) -> str:
        """
        The number under the rack's name: short enough to fit a cabinet, unlike the legend's
        own label, which is a sentence.
        """
        fraction = self.fraction
        return f'{fraction * 100:.0f}%' if fraction is not None else ''

    # The SVG group is translated to the rack's centre so that rotating it does not move it,
    # which means the shapes inside are drawn from half a footprint back. Computed here rather
    # than in the template: a Django template cannot divide, and expressing it there took a
    # stack of nested transforms to say what these two lines say.

    @property
    def offset_x(self) -> float:
        return -self.width / 2

    @property
    def offset_y(self) -> float:
        return -self.depth / 2

    # ---- the gauge along the cabinet's base ----
    #
    # A band alone cannot tell 12% from 48%: both are "under 50%" and both draw the same green
    # box, which is why a whole room came out one colour and said nothing. The gauge carries
    # the magnitude the band rounds away, and it sits in a strip at the foot of the cabinet so
    # it never competes with the name above it.

    @property
    def gauge_height(self) -> float:
        return max(8.0, self.depth * 0.17)

    @property
    def gauge_y(self) -> float:
        return self.depth / 2 - self.gauge_height - 3

    @property
    def gauge_track_width(self) -> float:
        return self.width - 10

    @property
    def gauge_width(self) -> float:
        fraction = self.fraction
        return self.gauge_track_width * (fraction or 0)

    @property
    def gauge_x(self) -> float:
        return -self.gauge_track_width / 2


def size_labels(placed: Sequence[PlacedRack]) -> None:
    """
    Give every rack on a floor the same label size, and trim the names that do not fit.

    Sizing each name to its own cabinet is the obvious rule and it draws badly: a plan of
    R101-long-name beside R103 came out with one name at four pixels and its neighbour at
    nineteen, which reads as a broken drawing rather than as a long name. One drawing gets one
    type size, exactly as a printed plan would.

    The size is set by the smallest cabinet on the floor, so the tightest fit is the one that
    decides, and anything longer than that cabinet can hold is trimmed with an ellipsis. The
    full name is still in the tooltip and in the hover card, so nothing is lost, only shortened.
    """
    if not placed:
        return

    narrowest = min(p.width for p in placed)
    shallowest = min(p.depth for p in placed)
    # Room for a name and, under it, the gauge's own reading.
    size = max(6.0, min(narrowest * 0.30, shallowest * 0.20))

    # 0.55 em per character is about right for a semi-bold sans-serif, which is what the
    # stylesheet sets. Two characters are held back for the ellipsis.
    for rack in placed:
        rack.label_size = size
        fits = max(2, int((rack.width - 6) / (size * 0.55)))
        name = rack.rack.name or ''
        rack.display_name = name if len(name) <= fits else f'{name[: fits - 1]}\u2026'


def metre_step(extent_cm: float) -> int:
    """
    How far apart to rule a plan of this size, in whole metres.

    The step opens up as the room grows, so a thirty-metre hall is not ruled every metre, and
    it stays a whole number, which is what somebody pacing a room out counts in.
    """
    metres = extent_cm / 100
    for candidate in (1, 2, 5, 10, 20, 50):
        if metres / candidate <= 12:
            return candidate
    return 50


def metre_ticks(extent_cm: float, step: int) -> list[tuple[float, str]]:
    """
    Where to rule one edge of the plan, and what to call each rule.

    The step is passed in rather than derived here, so both edges share it. Derived per axis it
    gave a room ruled every metre across and every two metres down, which reads as a drawing at
    two scales at once and makes a square on the grid a lie.
    """
    return [(tick * 100.0, str(tick)) for tick in range(0, int(extent_cm / 100) + 1, step)]


def natural_key(name: str | None) -> list[int | str]:
    """
    Sort key treating runs of digits as numbers, so R2 comes before R10.

    A plain string sort puts R10 between R1 and R2, which scrambles a row of racks named the
    way every rack in every data centre is named. net3d hit the same thing and solved it the
    same way; NetBox's own ordering does not do this for us here because the layout is built
    from a list rather than by the database.
    """
    parts = re.split(r'(\d+)', name or '')
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def autoplace_racks(
    racks: Iterable['Rack'], floor: 'Floor', gap: float = 15, aisle: float = 180
) -> list[tuple['Rack', float, float]]:
    """
    Lay racks out in rows, so a floor is worth opening before anybody has arranged it.

    One row per location, which is the closest thing NetBox has to a room, with racks in
    natural name order along it. Two spacings, because a data centre has two: a small `gap`
    between neighbouring cabinets in a row, and a much larger `aisle` between rows, which is
    where people and air actually go. Using one number for both produces a grid of boxes that
    looks nothing like a room.

    A row wider than the floor wraps rather than running off the edge, which net3d does not
    have to handle because its building is sized around the layout afterwards.

    This is a starting point, not a floor plan. It puts every rack somewhere sensible and
    leaves the operator to drag them into the real room.

    Returns a list of (rack, x, y) in centimetres, measured to each rack's centre. Racks that
    do not fit are left out rather than stacked off the edge, and the caller reports how many.
    """
    placed = []
    rows = {}
    for rack in racks:
        rows.setdefault(rack.location_id, []).append(rack)

    def row_order(item):
        location_id, _ = item
        # Racks with no location last, so a named room is never split by the unassigned ones.
        return (location_id is None, location_id or 0)

    y = aisle / 2
    for _, row_racks in sorted(rows.items(), key=row_order):
        row_depth = 0
        x = gap
        for rack in sorted(row_racks, key=lambda r: natural_key(r.name)):
            width, depth, _ = rack_footprint_cm(rack)
            # Wrap when this rack would cross the right-hand wall.
            if x + width > floor.width_cm - gap:
                x = gap
                y += row_depth + aisle
                row_depth = 0
            if y + depth > floor.depth_cm - gap:
                return placed
            placed.append((rack, x + width / 2, y + depth / 2))
            x += width + gap
            row_depth = max(row_depth, depth)
        y += row_depth + aisle

    return placed


@dataclass
class FloorViewport:
    """
    The box the plan is drawn in, and the sizes of the chrome around it.

    Everything here is in room centimetres, because the whole drawing is: the browser scales
    the viewBox to the card and nothing on the page computes a pixel. That is also why the type
    sizes are derived from the room rather than set in the stylesheet. A rule fixed at 11 px is
    11 px in a comms closet and 11 px in a thirty-metre hall, which means it is unreadable in
    one of them; a size in centimetres holds its apparent size at any scale.
    """

    width: float
    depth: float
    step: float

    @property
    def font(self) -> float:
        return max(self.width, self.depth) / 70

    @property
    def margin(self) -> float:
        return self.font * 3.2

    @property
    def tick_size(self) -> float:
        return self.font * 0.5

    @property
    def tick_gap(self) -> float:
        return self.font * 0.9

    @property
    def view_width(self) -> float:
        return self.width + self.margin * 1.4

    @property
    def view_depth(self) -> float:
        return self.depth + self.margin * 1.4


def floor_viewport(floor: 'Floor') -> FloorViewport:
    """
    The drawing box for one floor, including the margin its scale needs.

    The margin is on the top and left only, where the rules are, plus a little on the far
    edges so a rack against the wall is not clipped by the viewBox.
    """
    # The larger dimension sets the step, so a long thin room is not ruled finely across its
    # width and coarsely along its length.
    return FloorViewport(
        width=floor.width_cm,
        depth=floor.depth_cm,
        step=metre_step(max(floor.width_cm, floor.depth_cm)) * 100.0,
    )
